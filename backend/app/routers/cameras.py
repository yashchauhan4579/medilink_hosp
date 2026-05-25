import asyncio
from fastapi import APIRouter, HTTPException, Response
from fastapi.responses import StreamingResponse
import cv2
from app import database as db
from app.models import CameraCreate, CameraUpdate
from app.services.pipeline import pipeline_manager
from app.config import INFERENCE_FPS

router = APIRouter(prefix="/api/cameras", tags=["cameras"])


@router.get("")
def list_cameras():
    cameras = db.get_all_cameras()
    for cam in cameras:
        cam["pipeline"] = pipeline_manager.get_camera_status(cam["id"])
    return cameras


@router.post("")
def add_camera(data: CameraCreate):
    camera = db.create_camera(data.name, data.rtsp_url)
    if camera["enabled"]:
        pipeline_manager.start_camera(camera["id"], camera["rtsp_url"])
    return camera


@router.get("/{camera_id}")
def get_camera(camera_id: int):
    camera = db.get_camera(camera_id)
    if not camera:
        raise HTTPException(404, "Camera not found")
    camera["pipeline"] = pipeline_manager.get_camera_status(camera_id)
    camera["reception_config"] = db.get_module_config(camera_id, "reception")
    camera["crowd_config"] = db.get_module_config(camera_id, "crowd")
    camera["reception_roi"] = db.get_roi(camera_id, "reception")
    camera["crowd_roi"] = db.get_roi(camera_id, "crowd")
    return camera


@router.put("/{camera_id}")
def update_camera(camera_id: int, data: CameraUpdate):
    camera = db.get_camera(camera_id)
    if not camera:
        raise HTTPException(404, "Camera not found")
    updated = db.update_camera(camera_id, data.name, data.rtsp_url, data.enabled)
    if data.rtsp_url and data.rtsp_url != camera["rtsp_url"]:
        pipeline_manager.restart_camera(camera_id, data.rtsp_url)
    elif data.enabled is not None:
        if data.enabled:
            pipeline_manager.start_camera(camera_id, updated["rtsp_url"])
        else:
            pipeline_manager.stop_camera(camera_id)
    return updated


@router.delete("/{camera_id}")
def delete_camera(camera_id: int):
    camera = db.get_camera(camera_id)
    if not camera:
        raise HTTPException(404, "Camera not found")
    pipeline_manager.stop_camera(camera_id)
    db.delete_camera(camera_id)
    return {"ok": True}


@router.get("/modules/status")
def module_status():
    return pipeline_manager.get_module_status()


@router.get("/{camera_id}/snapshot")
def get_snapshot(camera_id: int):
    frame = pipeline_manager.grab_snapshot(camera_id)
    if frame is None:
        raise HTTPException(404, "No frame available. Camera may not be connected.")
    _, buf = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 90])
    return Response(content=buf.tobytes(), media_type="image/jpeg")


@router.get("/{camera_id}/stream")
async def mjpeg_stream(camera_id: int, raw: int = 0):
    camera = db.get_camera(camera_id)
    if not camera:
        raise HTTPException(404, "Camera not found")

    async def generate():
        interval = 1.0 / INFERENCE_FPS
        while True:
            jpeg = pipeline_manager.get_latest_jpeg(camera_id, raw=bool(raw))
            if jpeg:
                yield (
                    b"--frame\r\n"
                    b"Content-Type: image/jpeg\r\n\r\n" + jpeg + b"\r\n"
                )
            await asyncio.sleep(interval)

    return StreamingResponse(
        generate(),
        media_type="multipart/x-mixed-replace; boundary=frame",
    )
