from fastapi import APIRouter, HTTPException
from app import database as db
from app.models import RoiSave

router = APIRouter(prefix="/api/cameras/{camera_id}/roi", tags=["roi"])


@router.get("/{module}")
def get_roi(camera_id: int, module: str):
    if module not in ("reception", "crowd"):
        raise HTTPException(400, "Module must be 'reception' or 'crowd'")
    roi = db.get_roi(camera_id, module)
    if not roi:
        return {"camera_id": camera_id, "module": module, "polygon": None}
    return roi


@router.put("/{module}")
def save_roi(camera_id: int, module: str, data: RoiSave):
    if module not in ("reception", "crowd"):
        raise HTTPException(400, "Module must be 'reception' or 'crowd'")
    camera = db.get_camera(camera_id)
    if not camera:
        raise HTTPException(404, "Camera not found")
    if len(data.polygon) < 3:
        raise HTTPException(400, "Polygon must have at least 3 points")
    return db.save_roi(camera_id, module, data.polygon)
