"""Unit tests for the bounded model-upload reader (prevents OOM on the
free-tier instance when someone attempts a multi-GB transformer upload)."""
import asyncio

import pytest
from fastapi import HTTPException

from app.api.ml import MAX_CLASSICAL_ARTIFACT_BYTES, _read_limited_size


class _FakeUpload:
    """Minimal stand-in for Starlette's UploadFile (async read/close).

    Generates bytes lazily from a total size so an over-cap test doesn't
    need to materialise the whole (potentially huge) payload in memory.
    """

    def __init__(self, size: int, fill: bytes = b"z") -> None:
        self._size = size
        self._fill = fill
        self.closed = False

    async def read(self, n: int = -1) -> bytes:
        if self._size <= 0:
            return b""
        take = min(n, self._size)
        self._size -= take
        return self._fill * take

    async def close(self) -> None:
        self.closed = True


def test_read_limited_under_cap_returns_bytes():
    blob = b"x" * 1000
    out = asyncio.run(_read_limited_size(_FakeUpload(len(blob), blob[:1]), 2048))
    assert out == blob


def test_read_limited_over_cap_raises_413_and_closes():
    upload = _FakeUpload(MAX_CLASSICAL_ARTIFACT_BYTES + 1)
    with pytest.raises(HTTPException) as excinfo:
        asyncio.run(_read_limited_size(upload, MAX_CLASSICAL_ARTIFACT_BYTES))
    assert excinfo.value.status_code == 413
    assert upload.closed is True