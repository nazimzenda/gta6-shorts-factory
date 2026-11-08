from __future__ import annotations

import asyncio
import json

from fastapi import WebSocket
from starlette.websockets import WebSocketDisconnect

from app.services import FactoryService
from app.storage import store

_service = FactoryService(store)


def summary_payload() -> dict:
    payload = _service.dashboard_summary()
    payload["type"] = "summary"
    return payload


async def stream_dashboard(websocket: WebSocket) -> None:
    await websocket.accept()
    try:
        while True:
            await websocket.send_text(json.dumps(summary_payload(), default=str))
            await asyncio.sleep(2)
    except (WebSocketDisconnect, RuntimeError):
        return
