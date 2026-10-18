"""The fooddb-review CLI against a stub HTTP API (stdlib http.server). Unit suite: no database."""

import json
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from fooddb import reviewcli

FACETS = {"total": 1, "checks": {"energy-mismatch": 1}, "sources": {"fdc": 1}}
QUEUE = {"items": [{"record": "fdc:1", "pending": [{"observation_id": 7}]}]}


@pytest.fixture
def stub(monkeypatch):
    """A stub API on a loopback port. Observation 9 answers 409; the key fdb_bad is refused."""
    calls = []

    class Handler(BaseHTTPRequestHandler):
        def _serve(self):
            length = int(self.headers.get("content-length") or 0)
            posted = self.rfile.read(length) if length else b""
            path, _, qs = self.path.partition("?")
            calls.append({"method": self.command, "path": path, "query": dict(urllib.parse.parse_qsl(qs)),
                          "auth": self.headers.get("authorization"),
                          "json": json.loads(posted) if posted else None})
            if self.headers.get("authorization") == "Bearer fdb_bad":
                status, payload = 401, {"detail": "invalid or revoked API key"}
            elif self.command == "POST" and path.startswith("/v1/review/"):
                oid = int(path.rsplit("/", 1)[-1])
                status, payload = ((409, {"detail": f"observation {oid} is already rejected"}) if oid == 9
                                   else (200, {"id": oid, "status": "accepted", "reviewed_by": "agent"}))
            else:
                status, payload = {("GET", "/v1/review"): (200, QUEUE),
                                   ("GET", "/v1/review/facets"): (200, FACETS)}.get(
                                       (self.command, path), (404, {"detail": "no route"}))
            data = json.dumps(payload).encode()
            self.send_response(status)
            self.send_header("content-type", "application/json")
            self.send_header("content-length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        do_GET = do_POST = _serve

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    monkeypatch.setenv("FOODDB__REVIEW__URL", f"http://127.0.0.1:{server.server_port}")
    monkeypatch.setenv("FOODDB__REVIEW__KEY", "fdb_agent")
    yield calls
    server.shutdown()


def test_facets_prints_the_counts(stub, capsys):
    assert reviewcli.main(["facets", "--source", "fdc"]) == 0
    assert json.loads(capsys.readouterr().out) == FACETS
    (call,) = stub
    assert (call["method"], call["path"], call["auth"]) == ("GET", "/v1/review/facets", "Bearer fdb_agent")
    assert call["query"] == {"source": "fdc"}


def test_queue_passes_filters_paging_and_detail(stub, capsys):
    assert reviewcli.main(["queue", "--source", "recipe", "--check", "energy-mismatch",
                           "--limit", "2", "--offset", "40", "--detail"]) == 0
    assert stub[0]["query"] == {"source": "recipe", "check": "energy-mismatch", "limit": "2",
                                "offset": "40", "detail": "true"}
    assert json.loads(capsys.readouterr().out) == QUEUE


def test_decide_posts_each_id_and_a_409_is_reported_not_fatal(stub, capsys):
    assert reviewcli.main(["decide", "7", "9", "8", "--accept", "--by", "agent"]) == 0
    assert [c["json"] for c in stub] == [{"decision": "accept", "by": "agent"}] * 3
    assert [c["path"] for c in stub] == ["/v1/review/7", "/v1/review/9", "/v1/review/8"]
    lines = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert lines[0]["status"] == "accepted" and lines[2]["status"] == "accepted"
    assert lines[1]["id"] == 9 and lines[1]["error"] == "observation 9 is already rejected"


def test_decide_reject_sends_the_decision_and_note(stub, capsys):
    assert reviewcli.main(["decide", "7", "--reject", "--by", "agent", "--note", "10x typo"]) == 0
    assert stub[0]["json"] == {"decision": "reject", "by": "agent", "note": "10x typo"}
    assert json.loads(capsys.readouterr().out)["status"] == "accepted"  # the stub answers as it answers


def test_a_missing_key_fails_without_a_request(stub, monkeypatch, capsys):
    monkeypatch.delenv("FOODDB__REVIEW__KEY")
    assert reviewcli.main(["queue"]) != 0
    assert "FOODDB__REVIEW__KEY" in capsys.readouterr().err and stub == []


def test_a_refused_key_fails_and_is_never_echoed(stub, monkeypatch, capsys):
    monkeypatch.setenv("FOODDB__REVIEW__KEY", "fdb_bad")
    assert reviewcli.main(["queue"]) != 0
    out, err = capsys.readouterr()
    assert "401" in err and "fdb_bad" not in out + err


def test_a_dead_server_fails(stub, capsys):
    assert reviewcli.main(["queue", "--url", "http://127.0.0.1:1"]) != 0
    assert capsys.readouterr().err


def test_help_explains_checks_and_accept(capsys):
    for argv in (["queue", "--help"], ["decide", "--help"]):
        with pytest.raises(SystemExit) as e:
            reviewcli.main(argv)
        assert e.value.code == 0
    assert "energy-mismatch" in capsys.readouterr().out
