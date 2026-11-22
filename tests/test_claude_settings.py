"""Claude Code attribution stays off: no Co-Authored-By trailer on commits, no "Generated with" line on PRs."""

import json
from pathlib import Path

SETTINGS = Path(__file__).resolve().parent.parent / ".claude" / "settings.json"


def test_claude_attribution_is_off():
    s = json.loads(SETTINGS.read_text())
    assert s["attribution"] == {"commit": "", "pr": ""}
    assert s["includeCoAuthoredBy"] is False
