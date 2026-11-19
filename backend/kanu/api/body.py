"""Cuerpo JSON de la petición, venga o no con Content-Type (la interfaz actual no lo envía)."""
import json

from fastapi import Request


async def json_body(request: Request) -> dict:
    raw = await request.body()
    return json.loads(raw) if raw else {}
