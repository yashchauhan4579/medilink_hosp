from fastapi import APIRouter
from app import database as db
from app.models import ModuleConfigUpdate, SettingsUpdate

router = APIRouter(tags=["settings"])


@router.get("/api/settings")
def get_settings():
    return db.get_all_settings()


@router.put("/api/settings")
def update_settings(data: SettingsUpdate):
    db.update_settings(data.settings)
    return db.get_all_settings()


@router.get("/api/cameras/{camera_id}/config/{module}")
def get_module_config(camera_id: int, module: str):
    config = db.get_module_config(camera_id, module)
    if not config:
        return {"camera_id": camera_id, "module": module, "enabled": False}
    return config


@router.put("/api/cameras/{camera_id}/config/{module}")
def update_module_config(camera_id: int, module: str, data: ModuleConfigUpdate):
    return db.update_module_config(camera_id, module, **data.model_dump(exclude_none=True))
