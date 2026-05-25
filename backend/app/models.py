from pydantic import BaseModel
from typing import Optional


class CameraCreate(BaseModel):
    name: str
    rtsp_url: str


class CameraUpdate(BaseModel):
    name: Optional[str] = None
    rtsp_url: Optional[str] = None
    enabled: Optional[bool] = None


class RoiSave(BaseModel):
    polygon: list  # [[x, y], [x, y], ...] normalized 0-100


class ModuleConfigUpdate(BaseModel):
    enabled: Optional[bool] = None
    absence_timeout_sec: Optional[int] = None
    crowd_threshold: Optional[int] = None
    confidence_threshold: Optional[float] = None
    alert_cooldown_sec: Optional[int] = None


class SettingsUpdate(BaseModel):
    settings: dict
