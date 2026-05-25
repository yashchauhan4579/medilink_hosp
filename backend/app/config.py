import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent.parent
DATA_DIR = BASE_DIR / "data"
SNAPSHOTS_DIR = DATA_DIR / "snapshots"
MODELS_DIR = BASE_DIR / "models"

DATABASE_PATH = os.getenv("DATABASE_PATH", str(DATA_DIR / "hospital.db"))
MODEL_PATH = os.getenv("MODEL_PATH", str(MODELS_DIR / "best_head.engine"))
MODEL_PT_PATH = os.getenv("MODEL_PT_PATH", str(MODELS_DIR / "best_head.pt"))
PERSON_MODEL_PATH = os.getenv("PERSON_MODEL_PATH", str(MODELS_DIR / "yolov8n.engine"))
PERSON_MODEL_PT_PATH = os.getenv("PERSON_MODEL_PT_PATH", str(MODELS_DIR / "yolov8n.pt"))

INFERENCE_FPS = int(os.getenv("INFERENCE_FPS", "6"))
JPEG_QUALITY = int(os.getenv("JPEG_QUALITY", "70"))
STREAM_HEIGHT = int(os.getenv("STREAM_HEIGHT", "480"))

# Fight detection (Gemini / OpenRouter)
GEMINI_API_KEYS = [k for k in os.getenv("GEMINI_API_KEYS", "").split(",") if k.strip()]
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
OPENROUTER_MODEL = os.getenv("OPENROUTER_MODEL", "google/gemini-3.1-flash-lite")
FIGHT_COOLDOWN_SECONDS = int(os.getenv("FIGHT_COOLDOWN_SECONDS", "120"))
FIGHT_ANALYSIS_INTERVAL = int(os.getenv("FIGHT_ANALYSIS_INTERVAL", "6"))
FIGHT_CAMERA_IDS = [int(x) for x in os.getenv("FIGHT_CAMERA_IDS", "").split(",") if x.strip()]

# Sound detection
SOUND_DETECTION_ENABLED = os.getenv("SOUND_DETECTION_ENABLED", "true").lower() == "true"
SOUND_DB_THRESHOLD = float(os.getenv("SOUND_DB_THRESHOLD", "15"))
SOUND_COOLDOWN_SECONDS = int(os.getenv("SOUND_COOLDOWN_SECONDS", "30"))
SOUND_CALIBRATION_DURATION = int(os.getenv("SOUND_CALIBRATION_DURATION", "120"))
SOUND_SOURCE = os.getenv("SOUND_SOURCE", "mic")  # "mic" or "rtsp"

SNAPSHOTS_DIR.mkdir(parents=True, exist_ok=True)
DATA_DIR.mkdir(parents=True, exist_ok=True)
