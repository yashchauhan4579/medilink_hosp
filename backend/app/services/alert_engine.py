import time
import logging
import asyncio
import cv2
import threading
from dataclasses import dataclass, field
from typing import Optional
from datetime import datetime

from app import database as db
from app.config import SNAPSHOTS_DIR
from app.services.whatsapp import send_whatsapp_alert

logger = logging.getLogger(__name__)


@dataclass
class ReceptionState:
    absent_since: Optional[float] = None
    last_alert_time: Optional[float] = None
    active_alert_id: Optional[int] = None


@dataclass
class CrowdState:
    over_count: int = 0
    last_alert_time: Optional[float] = None


class AlertEngine:
    def __init__(self, stream_manager):
        self.stream_manager = stream_manager
        self._reception: dict[int, ReceptionState] = {}
        self._crowd: dict[int, CrowdState] = {}
        self._loop: Optional[asyncio.AbstractEventLoop] = None

    def set_loop(self, loop: asyncio.AbstractEventLoop):
        self._loop = loop

    def reset_camera(self, camera_id: int):
        self._reception.pop(camera_id, None)
        self._crowd.pop(camera_id, None)

    def update_reception(self, camera_id: int, heads_in_roi: int,
                         frame, camera_name: str):
        config = db.get_module_config(camera_id, "reception")
        if not config or not config["enabled"]:
            return

        state = self._reception.setdefault(camera_id, ReceptionState())
        now = time.monotonic()

        if heads_in_roi > 0:
            state.absent_since = None
            if state.active_alert_id:
                db.resolve_alert(state.active_alert_id)
                logger.info(f"Camera {camera_id}: reception alert {state.active_alert_id} resolved")
                state.active_alert_id = None
        else:
            if state.absent_since is None:
                state.absent_since = now
            elif (now - state.absent_since) >= config["absence_timeout_sec"]:
                cooldown = config.get("alert_cooldown_sec", 60)
                if state.last_alert_time is None or (now - state.last_alert_time) >= cooldown:
                    timeout_sec = config["absence_timeout_sec"]
                    alert = self._create_alert(
                        camera_id, "reception",
                        f"No attendant present on the reception for {timeout_sec}s — {camera_name}",
                        head_count=0, frame=frame, camera_name=camera_name,
                        extra={"absence_timeout_sec": timeout_sec},
                    )
                    state.active_alert_id = alert["id"]
                    state.last_alert_time = now

    def update_crowd(self, camera_id: int, heads_in_roi: int,
                     frame, camera_name: str):
        config = db.get_module_config(camera_id, "crowd")
        if not config or not config["enabled"]:
            return

        threshold = config["crowd_threshold"]
        state = self._crowd.setdefault(camera_id, CrowdState())
        now = time.monotonic()

        if heads_in_roi > threshold:
            state.over_count += 1
            if state.over_count >= 5:  # ~0.8s debounce at 6 FPS
                cooldown = config.get("alert_cooldown_sec", 60)
                if state.last_alert_time is None or (now - state.last_alert_time) >= cooldown:
                    self._create_alert(
                        camera_id, "crowd",
                        f"Crowd limit exceeded: {heads_in_roi} people detected — {camera_name}",
                        head_count=heads_in_roi, frame=frame, camera_name=camera_name,
                    )
                    state.last_alert_time = now
                    state.over_count = 0
        else:
            state.over_count = max(0, state.over_count - 1)

    def _create_alert(self, camera_id: int, module: str, message: str,
                      head_count: int, frame, camera_name: str,
                      extra: dict = None) -> dict:
        ts = int(time.time())
        snapshot_filename = f"{camera_id}_{module}_{ts}.jpg"
        snapshot_path = str(SNAPSHOTS_DIR / snapshot_filename)
        cv2.imwrite(snapshot_path, frame)

        alert = db.create_alert(camera_id, module, message, head_count, snapshot_filename)
        logger.info(f"ALERT [{module}] camera {camera_id}: {message}")

        # Build WhatsApp message
        alert_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        if module == "reception":
            timeout = (extra or {}).get("absence_timeout_sec", 30)
            wa_msg = f"🚨 *RECEPTION ALERT*\n\n"
            wa_msg += f"📷 Camera: {camera_name}\n"
            wa_msg += f"⚠️ No attendant present on the reception for {timeout} seconds\n"
            wa_msg += f"🕐 Time: {alert_time}"
        else:
            wa_msg = f"🚨 *CROWD ALERT*\n\n"
            wa_msg += f"📷 Camera: {camera_name}\n"
            wa_msg += f"👥 People count: {head_count}\n"
            wa_msg += f"🕐 Time: {alert_time}"

        def _send():
            result = send_whatsapp_alert(wa_msg, snapshot_path)
            wa_status = result.get("status", "error")
            db.update_alert_whatsapp_status(alert["id"], wa_status)
            if wa_status != "sent" and wa_status != "disabled":
                logger.warning(f"WhatsApp delivery failed for alert {alert['id']}: {result}")

        threading.Thread(target=_send, daemon=True).start()

        # Broadcast to dashboard WebSocket
        if self._loop:
            asyncio.run_coroutine_threadsafe(
                self.stream_manager.broadcast_alert(alert),
                self._loop,
            )

        return alert
