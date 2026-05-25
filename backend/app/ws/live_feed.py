from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from app.services.stream_manager import stream_manager

router = APIRouter()


@router.websocket("/ws/feed/{camera_id}")
async def feed_ws(websocket: WebSocket, camera_id: int):
    await websocket.accept()
    await stream_manager.subscribe_feed(camera_id, websocket)
    try:
        while True:
            await websocket.receive()
    except (WebSocketDisconnect, Exception):
        pass
    finally:
        stream_manager.unsubscribe_feed(camera_id, websocket)


@router.websocket("/ws/alerts")
async def alerts_ws(websocket: WebSocket):
    await websocket.accept()
    await stream_manager.subscribe_alerts(websocket)
    try:
        while True:
            await websocket.receive()
    except (WebSocketDisconnect, Exception):
        pass
    finally:
        stream_manager.unsubscribe_alerts(websocket)
