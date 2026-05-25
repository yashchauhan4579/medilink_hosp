import asyncio
import json
import logging
from collections import defaultdict
from fastapi import WebSocket

logger = logging.getLogger(__name__)


class StreamManager:
    def __init__(self):
        self._feed_subscribers: dict[int, set[WebSocket]] = defaultdict(set)
        self._alert_subscribers: set[WebSocket] = set()

    async def subscribe_feed(self, camera_id: int, ws: WebSocket):
        self._feed_subscribers[camera_id].add(ws)

    def unsubscribe_feed(self, camera_id: int, ws: WebSocket):
        self._feed_subscribers[camera_id].discard(ws)

    async def subscribe_alerts(self, ws: WebSocket):
        self._alert_subscribers.add(ws)

    def unsubscribe_alerts(self, ws: WebSocket):
        self._alert_subscribers.discard(ws)

    async def broadcast_meta(self, camera_id: int, meta: dict):
        msg = json.dumps({"type": "meta", "meta": meta})
        dead = []
        for ws in list(self._feed_subscribers.get(camera_id, set())):
            try:
                await ws.send_text(msg)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self._feed_subscribers[camera_id].discard(ws)

    async def broadcast_alert(self, alert: dict):
        msg = json.dumps({"type": "new_alert", "alert": alert})
        dead = []
        for ws in list(self._alert_subscribers):
            try:
                await ws.send_text(msg)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self._alert_subscribers.discard(ws)


stream_manager = StreamManager()
