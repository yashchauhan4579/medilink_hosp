import threading
from datetime import datetime
from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from typing import Optional
from app import database as db
from app.config import SNAPSHOTS_DIR
from app.services.whatsapp import send_whatsapp_alert

router = APIRouter(prefix="/api/alerts", tags=["alerts"])


@router.get("")
def list_alerts(camera_id: Optional[int] = None, module: Optional[str] = None,
                status: Optional[str] = None, limit: int = 50, offset: int = 0):
    return db.get_alerts(camera_id, module, status, limit, offset)


@router.get("/active-count")
def active_count():
    return {"count": db.get_active_alert_count()}


@router.post("/{alert_id}/acknowledge")
def acknowledge(alert_id: int):
    db.acknowledge_alert(alert_id)
    return {"ok": True}


@router.post("/{alert_id}/resolve")
def resolve(alert_id: int):
    db.resolve_alert(alert_id)
    return {"ok": True}


@router.post("/{alert_id}/send-whatsapp")
def send_whatsapp(alert_id: int):
    alerts = db.get_alerts(limit=1, offset=0)
    alert = None
    for a in db.get_alerts(limit=500, offset=0):
        if a["id"] == alert_id:
            alert = a
            break
    if not alert:
        raise HTTPException(404, "Alert not found")
    if alert.get("whatsapp_status") == "sent":
        return {"ok": True, "status": "already_sent"}

    # Build message
    alert_time = alert.get("created_at", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    wa_msg = f"\U0001f6a8 *FIGHT ALERT*\n\n"
    wa_msg += f"\U0001f4f7 Camera: {alert.get('camera_name', 'Unknown')}\n"
    wa_msg += f"\u26a0\ufe0f {alert.get('message', 'Fight detected')[:300]}\n"
    wa_msg += f"\U0001f550 Time: {alert_time}"

    # Prefer clip over snapshot for WhatsApp
    media_path = None
    if alert.get("clip_path"):
        clip = SNAPSHOTS_DIR / alert["clip_path"]
        if clip.exists():
            media_path = str(clip)
    if not media_path and alert.get("snapshot_path"):
        media_path = str(SNAPSHOTS_DIR / alert["snapshot_path"])

    result = send_whatsapp_alert(wa_msg, media_path)
    wa_status = result.get("status", "error")
    db.update_alert_whatsapp_status(alert_id, wa_status)
    return {"ok": wa_status in ("sent", "disabled"), "status": wa_status}


@router.get("/snapshot/{filename}")
def get_snapshot(filename: str):
    path = SNAPSHOTS_DIR / filename
    if not path.exists():
        raise HTTPException(404, "Snapshot not found")
    media_type = "video/mp4" if filename.endswith(".mp4") else "image/jpeg"
    return FileResponse(path, media_type=media_type)


@router.get("/clip/{filename}")
def get_clip(filename: str):
    # Check snapshots dir first (fight clips)
    path = SNAPSHOTS_DIR / filename
    if path.exists():
        return FileResponse(path, media_type="video/mp4")
    # Check sound_clips dir
    sound_clips_dir = SNAPSHOTS_DIR.parent / "sound_clips"
    path = sound_clips_dir / filename
    if path.exists():
        return FileResponse(path, media_type="video/mp4")
    raise HTTPException(404, "Clip not found")
