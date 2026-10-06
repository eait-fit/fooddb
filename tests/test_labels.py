"""Label reads without a database: each backend's parsing on canned answers, the photo rules, and the
stdio MCP tool. No test calls a real model: OpenRouter is a mock transport, the agent CLIs are fake
executables on PATH."""

import base64
import json
import os
import stat

import httpx
import pytest

from fooddb.labels import LabelRead, ReadFailed, backends, photos, reader

JPEG = b"\xff\xd8\xff\xe0" + b"\0" * 64
PNG = b"\x89PNG\r\n\x1a\n" + b"\0" * 64
WEBP = b"RIFF\x24\0\0\0WEBPVP8 " + b"\0" * 64
READ = {
    "values": {"ENERC_KCAL": 229, "ENERC_KJ": 958, "PROCNT": 7.4, "FAT": 17.1, "CHOCDF": None, "CHOAVL": 9.6,
               "SUGAR": 0.5, "FASAT": 2.0, "FIBTG": 6.0, "NA": 400},
    "basis": "100g", "serving_text": "2 tbsp (30 g)", "serving_g": 30, "name": "Hummus classic",
    "brand": "Acme", "barcode": "4006381333931", "lang": "de", "confidence": 0.93,
}


def check_read(r: LabelRead) -> None:
    assert r.values == {"ENERC_KCAL": 229, "ENERC_KJ": 958, "PROCNT": 7.4, "FAT": 17.1, "CHOAVL": 9.6,
                        "SUGAR": 0.5, "FASAT": 2.0, "FIBTG": 6.0, "NA": 400}  # nulls dropped
    assert (r.basis, r.serving_g, r.barcode, r.confidence) == ("100g", 30, "4006381333931", 0.93)


def test_a_read_is_parsed_strictly():
    from fooddb.labels import parse

    check_read(parse(json.dumps(READ)))
    check_read(parse("```json\n" + json.dumps(READ) + "\n```"))
    for bad in ("not json", "Sure! " + json.dumps(READ), json.dumps(READ | {"confidence": 1.5}),
                json.dumps(READ | {"values": {"KCAL": 1}}), json.dumps(READ | {"basis": "serving"}),
                json.dumps(READ | {"extra": 1}), json.dumps([READ])):
        with pytest.raises(ReadFailed):
            parse(bad)


def openrouter(handler) -> backends.OpenRouter:
    return backends.OpenRouter(api_key="sk-test", transport=httpx.MockTransport(handler))


def answer(content: str) -> httpx.Response:
    return httpx.Response(200, json={"choices": [{"message": {"content": content}}]})


def test_openrouter_sends_the_photo_and_a_json_schema_and_parses_the_answer():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"], seen["auth"], seen["body"] = str(request.url), request.headers["authorization"], json.loads(request.content)
        return answer(json.dumps(READ))

    check_read(openrouter(handler).read(PNG, "image/png", {"barcode": "4006381333931"}))
    body = seen["body"]
    assert seen["url"] == "https://openrouter.ai/api/v1/chat/completions" and seen["auth"] == "Bearer sk-test"
    assert body["model"] == "qwen/qwen3-vl-235b-a22b-instruct"
    assert body["response_format"]["type"] == "json_schema" and body["response_format"]["json_schema"]["strict"]
    [text, image] = body["messages"][0]["content"]
    assert "4006381333931" in text["text"]
    assert image["image_url"]["url"] == "data:image/png;base64," + base64.b64encode(PNG).decode()


def test_openrouter_model_is_switched_by_config(monkeypatch):
    monkeypatch.setenv("FOODDB__BACKEND__LLM_MODEL", "x-ai/grok-4")
    seen = {}

    def handler(request):
        seen.update(json.loads(request.content))
        return answer(json.dumps(READ))

    openrouter(handler).read(JPEG, "image/jpeg", {})
    assert seen["model"] == "x-ai/grok-4"


def test_openrouter_retries_transient_failures_then_gives_up(monkeypatch):
    monkeypatch.setattr(backends.time, "sleep", lambda s: None)
    calls = []

    def flaky(request):
        calls.append(1)
        if len(calls) == 1:
            raise httpx.ConnectError("down")
        return httpx.Response(503) if len(calls) == 2 else answer(json.dumps(READ))

    check_read(openrouter(flaky).read(JPEG, "image/jpeg", {}))
    assert len(calls) == 3
    calls.clear()
    with pytest.raises(ReadFailed, match="503"):
        openrouter(lambda r: calls.append(1) or httpx.Response(503)).read(JPEG, "image/jpeg", {})
    assert len(calls) == backends.RETRIES + 1
    calls.clear()
    with pytest.raises(ReadFailed, match="401"):  # a refused key is not retried
        openrouter(lambda r: calls.append(1) or httpx.Response(401)).read(JPEG, "image/jpeg", {})
    assert len(calls) == 1
    with pytest.raises(ReadFailed):
        openrouter(lambda r: answer("I cannot read this label.")).read(JPEG, "image/jpeg", {})


def test_openrouter_needs_a_key(monkeypatch):
    monkeypatch.delenv("FOODDB__BACKEND__LLM_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="FOODDB__BACKEND__LLM_API_KEY"):
        backends.OpenRouter()


def fake_cli(tmp_path, monkeypatch, name: str, script: str) -> None:
    """A fake agent CLI first on PATH. It logs its arguments and the image it was given."""
    exe = tmp_path / "bin" / name
    exe.parent.mkdir(exist_ok=True)
    exe.write_text("#!/usr/bin/env python3\nimport json, os, sys\nargs = sys.argv[1:]\n"
                   f"json.dump(args, open({str(tmp_path / 'args.json')!r}, 'w'))\n" + script)
    exe.chmod(exe.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("PATH", f"{exe.parent}{os.pathsep}{os.environ['PATH']}")


def logged_args(tmp_path) -> list[str]:
    return json.loads((tmp_path / "args.json").read_text())


def test_claude_cli_reads_the_photo_from_a_file_and_returns_structured_output(tmp_path, monkeypatch):
    fake_cli(tmp_path, monkeypatch, "claude", f"""
prompt = args[args.index('-p') + 1]
path = prompt.split('The label photo is the file ')[1].split()[0].rstrip('.')
assert open(path, 'rb').read().startswith(b'\\x89PNG'), path
assert json.loads(args[args.index('--json-schema') + 1])['type'] == 'object'
print(json.dumps({{"type": "result", "is_error": False, "result": "", "structured_output": {READ!r}}}))
""")
    check_read(backends.AgentCli("claude").read(PNG, "image/png", {}))
    args = logged_args(tmp_path)
    assert args[args.index("--output-format") + 1] == "json" and args[args.index("--tools") + 1] == "Read"


def test_claude_cli_falls_back_to_the_result_text_and_refuses_errors(tmp_path, monkeypatch):
    fake_cli(tmp_path, monkeypatch, "claude", f"print(json.dumps({{'is_error': False, 'result': {json.dumps(json.dumps(READ))}}}))")
    check_read(backends.AgentCli("claude").read(JPEG, "image/jpeg", {}))
    fake_cli(tmp_path, monkeypatch, "claude", "print(json.dumps({'is_error': True, 'result': 'Credit balance is too low'}))")
    with pytest.raises(ReadFailed, match="Credit balance"):
        backends.AgentCli("claude").read(JPEG, "image/jpeg", {})
    fake_cli(tmp_path, monkeypatch, "claude", "print('Here is the label: ...')")
    with pytest.raises(ReadFailed):
        backends.AgentCli("claude").read(JPEG, "image/jpeg", {})
    fake_cli(tmp_path, monkeypatch, "claude", "sys.stderr.write('not logged in'); sys.exit(1)")
    with pytest.raises(ReadFailed, match="not logged in"):
        backends.AgentCli("claude").read(JPEG, "image/jpeg", {})


def test_codex_cli_passes_the_image_and_schema_and_reads_the_last_message(tmp_path, monkeypatch):
    fake_cli(tmp_path, monkeypatch, "codex", f"""
assert args[0] == 'exec'
image = args[args.index('--image') + 1]
assert open(image, 'rb').read().startswith(b'RIFF'), image
assert args[args.index('--image') + 2] == '--', args
assert json.load(open(args[args.index('--output-schema') + 1]))['type'] == 'object'
open(args[args.index('--output-last-message') + 1], 'w').write({json.dumps(json.dumps(READ))})
""")
    check_read(backends.AgentCli("codex").read(WEBP, "image/webp", {"name": "Hummus"}))
    args = logged_args(tmp_path)
    assert "Hummus" in args[-1] and args[args.index("--sandbox") + 1] == "read-only"


def test_an_agent_cli_that_hangs_times_out(tmp_path, monkeypatch):
    fake_cli(tmp_path, monkeypatch, "codex", "import time; time.sleep(10)")
    monkeypatch.setattr(backends, "AGENT_TIMEOUT", 0.5)
    with pytest.raises(ReadFailed, match="no answer"):
        backends.AgentCli("codex").read(JPEG, "image/jpeg", {})


def test_an_agent_cli_must_be_installed(monkeypatch, tmp_path):
    monkeypatch.setenv("PATH", str(tmp_path))
    with pytest.raises(RuntimeError, match="claude"):
        backends.AgentCli("claude")


def test_the_reader_is_chosen_by_config(monkeypatch):
    monkeypatch.delenv("FOODDB__BACKEND__LABEL_READER", raising=False)
    monkeypatch.delenv("FOODDB__BACKEND__LLM_API_KEY", raising=False)
    assert isinstance(reader(), backends.Demo)
    monkeypatch.setenv("FOODDB__BACKEND__LLM_API_KEY", "sk-test")
    assert isinstance(reader(), backends.OpenRouter)
    monkeypatch.setenv("FOODDB__BACKEND__LABEL_READER", "demo")
    assert isinstance(reader(), backends.Demo)
    with pytest.raises(ValueError):
        reader("gpt")


def test_the_demo_reader_is_never_trusted():
    r = backends.Demo().read(JPEG, "image/jpeg", {"barcode": "4006381333931"})
    assert r.confidence == 0 and r.barcode == "4006381333931" and r.values["ENERC_KCAL"] > 0


def test_photos_are_sniffed_by_their_bytes_not_their_name():
    assert [photos.check(b) for b in (JPEG, PNG, WEBP)] == ["image/jpeg", "image/png", "image/webp"]
    for bad in (b"GIF89a" + b"\0" * 64, b"%PDF-1.7", b"<svg xmlns='http://www.w3.org/2000/svg'/>", b"RIFF\0\0\0\0WAVE", b""):
        with pytest.raises(photos.Refused) as e:
            photos.check(bad)
        assert e.value.status == 415


def test_photos_over_the_size_limit_are_refused():
    with pytest.raises(photos.Refused) as e:
        photos.check(JPEG + b"\0" * photos.MAX_BYTES)
    assert e.value.status == 413


def test_photos_are_stored_once_by_content_hash(tmp_path, monkeypatch):
    import hashlib

    monkeypatch.setenv("FOODDB__BACKEND__PHOTO_DIR", str(tmp_path))
    sha, mime = photos.store(PNG)
    assert sha == hashlib.sha256(PNG).hexdigest() and mime == "image/png"
    assert photos.store(PNG) == (sha, mime)
    assert [p.name for p in tmp_path.rglob("*") if p.is_file()] == [sha]
    assert photos.load(sha) == PNG
    for bad in ("../../etc/passwd", "0" * 64, sha.upper()):
        with pytest.raises(LookupError):
            photos.load(bad)


def mcp_call(tool: str, **args):
    import anyio
    from mcp import Client

    from fooddb.api import mcp

    async def go():
        async with Client(mcp) as c:
            return await c.call_tool(tool, args)

    return anyio.run(go)


def test_mcp_read_label_on_stdio_reads_locally_without_a_key_or_a_server(monkeypatch):
    def nowhere(*a, **kw):
        raise AssertionError("read_label without submit must not call any server")

    monkeypatch.setattr(httpx, "post", nowhere)
    monkeypatch.delenv("FOODDB__BACKEND__DATABASE_URL", raising=False)
    image = base64.b64encode(JPEG).decode()
    r = mcp_call("read_label", image=image, barcode="4006381333931", reader="demo")
    assert not r.is_error, r.content
    read = r.structured_content["read"]
    assert read["barcode"] == "4006381333931" and read["values"]["ENERC_KCAL"] > 0
    assert "submitted" not in r.structured_content
    assert mcp_call("read_label", image=base64.b64encode(b"GIF89a").decode(), reader="demo").is_error
    assert mcp_call("read_label", image="%%%", reader="demo").is_error


def test_mcp_read_label_submit_needs_a_configured_server(monkeypatch):
    monkeypatch.delenv("FOODDB__BACKEND__SUBMIT_URL", raising=False)
    r = mcp_call("read_label", image=base64.b64encode(JPEG).decode(), reader="demo", submit=True)
    assert r.is_error and "FOODDB__BACKEND__SUBMIT_URL" in r.content[0].text
