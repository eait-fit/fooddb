"""Label photos: JPEG, PNG or WebP by their magic bytes, stored once under their SHA-256."""

import hashlib
import os
import re
import tempfile
from pathlib import Path

MAX_BYTES = 10 * 1024 * 1024
SHA = re.compile(r"[0-9a-f]{64}")


class Refused(ValueError):
    def __init__(self, message: str, status: int):
        super().__init__(message)
        self.status = status


def sniff(data: bytes) -> str | None:
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return None


def check(data: bytes) -> str:
    if len(data) > MAX_BYTES:
        raise Refused(f"a photo is at most {MAX_BYTES} bytes", 413)
    if (mime := sniff(data)) is None:
        raise Refused("a photo must be JPEG, PNG or WebP", 415)
    return mime


def directory() -> Path:
    return Path(os.environ.get("FOODDB__BACKEND__PHOTO_DIR", "photos"))


def _path(sha: str) -> Path:
    return directory() / sha[:2] / sha


def store(data: bytes) -> tuple[str, str]:
    """Checked, then written once (atomically) under its hash. Returns (sha256, media type)."""
    mime = check(data)
    sha = hashlib.sha256(data).hexdigest()
    path = _path(sha)
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as tmp:
            tmp.write(data)
        os.replace(tmp.name, path)
    return sha, mime


def load(sha: str) -> bytes:
    if not SHA.fullmatch(sha) or not (path := _path(sha)).is_file():
        raise LookupError(f"no photo {sha}")
    return path.read_bytes()
