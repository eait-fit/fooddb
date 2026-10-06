"""Helpers the fetchers share: a download streamed to disk, and a JSON array read item by item."""

import codecs
import hashlib
import json
import re
from collections.abc import Iterator
from typing import BinaryIO

import httpx


def download(url: str, to: BinaryIO) -> str:
    """Stream `url` into the open file `to` and rewind it. Returns the SHA-256 of the body."""
    digest = hashlib.sha256()
    with httpx.stream("GET", url, timeout=httpx.Timeout(60, read=600), follow_redirects=True) as r:
        r.raise_for_status()
        for chunk in r.iter_bytes():
            to.write(chunk)
            digest.update(chunk)
    to.seek(0)
    return digest.hexdigest()


def json_items(f: BinaryIO, key: str, chunk: int = 1 << 20) -> Iterator:
    """The items of the array under `key` in a JSON document, read `chunk` bytes at a time. Memory
    holds one item, however large the file. ponytail: finds `"key": [` by text, so the key must not
    occur earlier in the document; and items must be objects or arrays, as in every source we read."""
    decode = codecs.getincrementaldecoder("utf-8")().decode
    dec = json.JSONDecoder()
    buf, pos, eof = "", 0, False

    def more() -> None:
        nonlocal buf, pos, eof
        got = f.read(chunk)
        eof = not got
        buf, pos = buf[pos:] + decode(got, final=eof), 0

    start = re.compile(rf'"{re.escape(key)}"\s*:\s*\[')
    while not (m := start.search(buf)):
        if eof:
            raise ValueError(f"no array {key!r} in the document")
        more()
    pos = m.end()
    while True:
        while pos < len(buf) and buf[pos] in " \t\r\n,":
            pos += 1
        if pos == len(buf):
            if eof:
                raise ValueError(f"array {key!r} ends early")
            more()
            continue
        if buf[pos] == "]":
            return
        try:
            item, pos = dec.raw_decode(buf, pos)
        except json.JSONDecodeError:
            if eof:
                raise
            more()  # the item runs past what is read so far
            continue
        yield item
