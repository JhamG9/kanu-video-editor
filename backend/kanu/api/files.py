"""Envío de archivos grandes con soporte de Range (el <video> del navegador lo necesita para avanzar)."""
from pathlib import Path

from fastapi import Request
from fastapi.responses import Response, StreamingResponse

CHUNK = 1 << 20


def send_file(path: Path, ctype: str, request: Request) -> Response:
    size = path.stat().st_size
    a, b, status = 0, size - 1, 200
    rng = request.headers.get("range")
    if rng and rng.startswith("bytes="):
        s, _, e = rng[6:].partition("-")
        if s:
            a, b = int(s), (int(e) if e else size - 1)
        else:
            a = max(0, size - int(e))
        b, status = min(b, size - 1), 206

    def body():
        with open(path, "rb") as fh:
            fh.seek(a)
            left = b - a + 1
            while left > 0:
                chunk = fh.read(min(CHUNK, left))
                if not chunk:
                    break
                left -= len(chunk)
                yield chunk

    headers = {"Accept-Ranges": "bytes", "Content-Length": str(b - a + 1), "Cache-Control": "no-store"}
    if status == 206:
        headers["Content-Range"] = f"bytes {a}-{b}/{size}"
    return StreamingResponse(body(), status_code=status, media_type=ctype, headers=headers)
