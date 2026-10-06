"""The GS1 verification port, without a database."""

import pytest

from fooddb import gs1


def test_the_default_verifier_answers_unknown(monkeypatch):
    monkeypatch.delenv("FOODDB__BACKEND__GS1_VERIFIER", raising=False)
    assert gs1.verifier().verify("04006381333931", "Acme") == "unknown"
    assert gs1.check("04006381333931", "Acme") == "unknown"


def test_an_unknown_backend_name_is_refused(monkeypatch):
    monkeypatch.setenv("FOODDB__BACKEND__GS1_VERIFIER", "gepir")
    with pytest.raises(ValueError, match="none"):
        gs1.verifier()


@pytest.mark.parametrize("answer", ["verified", "not_verified", "unknown"])
def test_check_passes_a_verifiers_verdict_through(monkeypatch, answer):
    monkeypatch.setattr(gs1, "verifier", lambda name=None: type("V", (), {"verify": lambda self, g, b: answer})())
    assert gs1.check("04006381333931", "Acme") == answer


@pytest.mark.parametrize("bad", ["yes", None, True])
def test_a_verdict_outside_the_three_is_unknown(monkeypatch, bad):
    monkeypatch.setattr(gs1, "verifier", lambda name=None: type("V", (), {"verify": lambda self, g, b: bad})())
    assert gs1.check("04006381333931", "Acme") == "unknown"


def test_a_verifier_that_raises_is_unknown(monkeypatch):
    def boom(self, g, b):
        raise RuntimeError("GS1 is down")

    monkeypatch.setattr(gs1, "verifier", lambda name=None: type("V", (), {"verify": boom})())
    assert gs1.check("04006381333931", "Acme") == "unknown"
