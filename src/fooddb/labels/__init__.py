"""The model port for label reads: a vision model reads a nutrition label photo into per-100 values.

`reader()` picks the backend from FOODDB__BACKEND__LABEL_READER: `openrouter` (the hosted pipeline),
`claude-cli` and `codex-cli` (local agents on the user's own subscription) or `demo` (canned).
Every backend answers with the same JSON schema, parsed strictly into a `LabelRead`.
"""

import json
import math
import os
from typing import Literal, Protocol

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

NUTRIENTS = ("ENERC_KCAL", "ENERC_KJ", "PROCNT", "FAT", "CHOCDF", "CHOAVL", "SUGAR", "FASAT", "FIBTG", "NA")
READERS = ("openrouter", "claude-cli", "codex-cli", "demo")


class ReadFailed(RuntimeError):
    pass


class LabelRead(BaseModel):
    model_config = ConfigDict(extra="forbid")

    values: dict[str, float]  # per 100 g or 100 ml (basis), INFOODS tagname → value; NA in mg
    basis: Literal["100g", "100ml"]
    serving_text: str | None = None
    serving_g: float | None = Field(None, gt=0)
    name: str | None = None
    brand: str | None = None
    barcode: str | None = None
    lang: str | None = None
    confidence: float = Field(ge=0, le=1)

    @field_validator("values", mode="before")
    @classmethod
    def _known_codes(cls, v):
        if not isinstance(v, dict):
            return v
        if unknown := set(v) - set(NUTRIENTS):
            raise ValueError(f"unknown nutrient codes: {sorted(unknown)}")
        out = {k: x for k, x in v.items() if x is not None}
        if any(not isinstance(x, int | float) or isinstance(x, bool) or not math.isfinite(x) for x in out.values()):
            raise ValueError("values must be finite numbers")
        return out


_nullable = {"type": ["string", "null"]}
SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["values", "basis", "serving_text", "serving_g", "name", "brand", "barcode", "lang", "confidence"],
    "properties": {
        "values": {"type": "object", "additionalProperties": False, "required": list(NUTRIENTS),
                   "properties": {k: {"type": ["number", "null"]} for k in NUTRIENTS}},
        "basis": {"type": "string", "enum": ["100g", "100ml"]},
        "serving_text": _nullable, "serving_g": {"type": ["number", "null"]},
        "name": _nullable, "brand": _nullable, "barcode": _nullable, "lang": _nullable,
        "confidence": {"type": "number"},
    },
}

PROMPT = """Read the nutrition label in the photo. Answer with one JSON object that follows the schema, and nothing else.

- values: per 100 g (basis "100g") or per 100 ml (basis "100ml"), as the label states them. If the label
  states only per serving, compute per 100 from the serving size, or give null when you cannot.
  ENERC_KCAL kcal, ENERC_KJ kJ (only when printed), PROCNT protein g, FAT g, FASAT saturates g,
  SUGAR sugars g, FIBTG fibre g, NA sodium mg (if only salt is printed: salt g × 400).
- Carbohydrate: CHOAVL when it excludes fibre (EU, UK, Switzerland, Norway, Australia, New Zealand
  labels). CHOCDF when it includes fibre ("Total Carbohydrate", US and Canada). Give one, the other null.
- A value you cannot read is null. Never guess a value.
- serving_text as printed, serving_g in grams when printed; name and brand as printed; barcode the
  digits under the barcode when visible; lang the ISO 639-1 code of the label text.
- confidence: 0 to 1, how sure you are that every non-null value is read correctly."""


def prompt(hints: dict[str, str]) -> str:
    said = "; ".join(f"{k}: {v}" for k, v in hints.items() if v)
    return PROMPT + (f"\n\nThe uploader says (it may be wrong): {said}." if said else "")


def parse(answer: str | dict) -> LabelRead:
    """One JSON object, at most wrapped in a single code fence. Nothing else is searched for."""
    try:
        if isinstance(answer, str):
            text = answer.strip()
            if text.startswith("```"):
                text = text.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
            answer = json.loads(text)
        if not isinstance(answer, dict):
            raise ReadFailed("the answer is not a JSON object")
        return LabelRead.model_validate(answer)
    except (ValueError, ValidationError) as e:
        raise ReadFailed(f"not a label read: {e}") from e


class LabelReader(Protocol):
    def read(self, image: bytes, mime: str, hints: dict[str, str]) -> LabelRead: ...


def reader(name: str | None = None) -> LabelReader:
    from fooddb.labels import backends

    name = (name or os.environ.get("FOODDB__BACKEND__LABEL_READER")
            or ("openrouter" if os.environ.get("FOODDB__BACKEND__LLM_API_KEY") else "demo"))
    if name not in READERS:
        raise ValueError(f"label reader must be one of {', '.join(READERS)}, not {name!r}")
    if name == "openrouter":
        return backends.OpenRouter()
    if name == "demo":
        return backends.Demo()
    return backends.AgentCli(name.removesuffix("-cli"))


def submit(image: bytes, hints: dict[str, str], read: LabelRead) -> dict:
    """Send a local read and its photo to a fooddb server, with the user's contribute key."""
    url, key = os.environ.get("FOODDB__BACKEND__SUBMIT_URL"), os.environ.get("FOODDB__BACKEND__SUBMIT_KEY")
    if not url or not key:
        raise RuntimeError("set FOODDB__BACKEND__SUBMIT_URL and FOODDB__BACKEND__SUBMIT_KEY to submit a read")
    r = httpx.post(f"{url.rstrip('/')}/v1/labels", files={"photo": ("label", image)},
                   data=hints | {"read": read.model_dump_json()},
                   headers={"Authorization": f"Bearer {key}"}, timeout=60)
    if r.status_code >= 400:
        raise RuntimeError(f"{url} refused the read: {r.status_code} {r.text[:300]}")
    return r.json()
