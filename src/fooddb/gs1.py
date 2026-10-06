"""The GS1 verification port: does GS1 say this brand owns this barcode's company prefix?

`verifier()` picks the backend from FOODDB__BACKEND__GS1_VERIFIER. Only `none` exists: it answers
`unknown` for everything, so every brand upload waits for review. A real backend (GS1 access has a
cost, see docs/decisions.md) is a class with `verify` added to `VERIFIERS`.
"""

import logging
import os
from typing import Literal, Protocol

Verdict = Literal["verified", "not_verified", "unknown"]
VERDICTS = ("verified", "not_verified", "unknown")


class Gs1Verifier(Protocol):
    def verify(self, gtin14: str, claimed_brand: str) -> Verdict: ...


class NoVerifier:
    def verify(self, gtin14: str, claimed_brand: str) -> Verdict:
        return "unknown"


VERIFIERS = {"none": NoVerifier}


def verifier(name: str | None = None) -> Gs1Verifier:
    name = name or os.environ.get("FOODDB__BACKEND__GS1_VERIFIER") or "none"
    if name not in VERIFIERS:
        raise ValueError(f"GS1 verifier must be one of {', '.join(VERIFIERS)}, not {name!r}")
    return VERIFIERS[name]()


def check(gtin14: str, claimed_brand: str) -> Verdict:
    """The verdict of the configured verifier. A failing or odd verifier counts as `unknown`: never as verified."""
    try:
        answer = verifier().verify(gtin14, claimed_brand)
    except Exception:
        logging.getLogger(__name__).exception("GS1 verifier failed")
        return "unknown"
    return answer if answer in VERDICTS else "unknown"
