"""Label reader backends: OpenRouter over HTTP, Claude Code and Codex CLI as subprocesses, and a demo."""

import base64
import json
import os
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

import httpx

from fooddb.labels import SCHEMA, LabelRead, ReadFailed, parse, prompt

DEFAULT_MODEL = "qwen/qwen3-vl-235b-a22b-instruct"  # the OpenRouter account reaches x-ai and Chinese vendors only
TIMEOUT = 120
RETRIES = 2
AGENT_TIMEOUT = 300
EXTENSIONS = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp"}


class OpenRouter:
    def __init__(self, api_key: str | None = None, transport: httpx.BaseTransport | None = None):
        self.api_key = api_key or os.environ.get("FOODDB__BACKEND__LLM_API_KEY")
        if not self.api_key:
            raise RuntimeError("the openrouter label reader needs FOODDB__BACKEND__LLM_API_KEY")
        self.model = os.environ.get("FOODDB__BACKEND__LLM_MODEL") or DEFAULT_MODEL
        self.transport = transport

    def read(self, image: bytes, mime: str, hints: dict[str, str]) -> LabelRead:
        body = {
            "model": self.model,
            "temperature": 0,
            "messages": [{"role": "user", "content": [
                {"type": "text", "text": prompt(hints)},
                {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{base64.b64encode(image).decode()}"}},
            ]}],
            "response_format": {"type": "json_schema", "json_schema": {"name": "label_read", "strict": True, "schema": SCHEMA}},
            "provider": {"require_parameters": True},  # only providers that honour the schema
        }
        failure = ""
        with httpx.Client(transport=self.transport, timeout=TIMEOUT) as c:
            for attempt in range(RETRIES + 1):
                if attempt:
                    time.sleep(2 ** attempt)
                try:
                    r = c.post("https://openrouter.ai/api/v1/chat/completions", json=body,
                               headers={"Authorization": f"Bearer {self.api_key}"})
                except httpx.TransportError as e:
                    failure = repr(e)
                    continue
                if r.status_code == 429 or r.status_code >= 500:
                    failure = f"HTTP {r.status_code}"
                    continue
                if r.status_code >= 400:
                    raise ReadFailed(f"openrouter: HTTP {r.status_code}: {r.text[:300]}")
                try:
                    content = r.json()["choices"][0]["message"]["content"]
                except (ValueError, KeyError, IndexError, TypeError) as e:
                    raise ReadFailed(f"openrouter: unexpected answer: {r.text[:300]}") from e
                return parse(content)
        raise ReadFailed(f"openrouter: gave up after {RETRIES + 1} attempts: {failure}")


class AgentCli:
    """A local agent on the user's own subscription: `claude -p` or `codex exec`, with the photo as a file."""

    def __init__(self, kind: str):
        self.kind = kind
        self.exe = shutil.which(kind)
        if self.exe is None:
            raise RuntimeError(f"the {kind}-cli label reader needs `{kind}` on PATH")

    def read(self, image: bytes, mime: str, hints: dict[str, str]) -> LabelRead:
        with tempfile.TemporaryDirectory() as d:
            photo = Path(d) / f"label{EXTENSIONS[mime]}"
            photo.write_bytes(image)
            out = Path(d) / "read.json"
            if self.kind == "claude":
                cmd = [self.exe, "-p", f"{prompt(hints)}\n\nThe label photo is the file {photo} .",
                       "--output-format", "json", "--json-schema", json.dumps(SCHEMA), "--tools", "Read", "--add-dir", d]
            else:
                schema = Path(d) / "schema.json"
                schema.write_text(json.dumps(SCHEMA))
                cmd = [self.exe, "exec", "--skip-git-repo-check", "--sandbox", "read-only",
                       "--output-schema", str(schema), "--output-last-message", str(out),
                       "--image", str(photo), "--", prompt(hints)]
            try:
                p = subprocess.run(cmd, cwd=d, capture_output=True, text=True, timeout=AGENT_TIMEOUT,
                                   stdin=subprocess.DEVNULL)
            except subprocess.TimeoutExpired as e:
                raise ReadFailed(f"{self.kind}: no answer within {AGENT_TIMEOUT} s") from e
            if p.returncode:
                raise ReadFailed(f"{self.kind} exited {p.returncode}: {(p.stderr or p.stdout)[-500:]}")
            if self.kind == "codex":
                return parse(out.read_text() if out.exists() else "")
            try:
                result = json.loads(p.stdout)
            except ValueError as e:
                raise ReadFailed(f"claude: not JSON output: {p.stdout[:300]}") from e
            if not isinstance(result, dict) or result.get("is_error"):
                raise ReadFailed(f"claude: {str(result.get('result') if isinstance(result, dict) else result)[:300]}")
            return parse(result.get("structured_output") or result.get("result") or "")


DEMO_VALUES = {"ENERC_KCAL": 229.0, "PROCNT": 7.4, "FAT": 17.1, "CHOAVL": 9.6, "SUGAR": 0.5, "FASAT": 2.0,
               "FIBTG": 6.0, "NA": 400.0}


class Demo:
    """Canned, for tests and for a server without an LLM key. Its confidence is 0: nothing it reads is served
    without review."""

    def read(self, image: bytes, mime: str, hints: dict[str, str]) -> LabelRead:
        return LabelRead(values=DEMO_VALUES, basis="100g", serving_text="2 tbsp (30 g)", serving_g=30,
                         name=hints.get("name") or "Demo hummus", brand="Demo", barcode=hints.get("barcode"),
                         lang="en", confidence=0)
