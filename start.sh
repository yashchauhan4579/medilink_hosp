#!/bin/bash
cd /home/jetson/hospital-monitor/backend

# Load environment variables from .env if present
if [ -f ../.env ]; then
  set -a; source ../.env; set +a
fi

# Fight detection (OpenRouter)
export OPENROUTER_API_KEY="${OPENROUTER_API_KEY:-}"
export OPENROUTER_MODEL="${OPENROUTER_MODEL:-google/gemini-3.1-flash-lite}"

# Fight detection camera config
export FIGHT_CAMERA_IDS="${FIGHT_CAMERA_IDS:-}"
export FIGHT_COOLDOWN_SECONDS="${FIGHT_COOLDOWN_SECONDS:-120}"

# Gemini keys (fallback for fight detection)
export GEMINI_API_KEYS="${GEMINI_API_KEYS:-}"

# Sound detection
export SOUND_DETECTION_ENABLED="${SOUND_DETECTION_ENABLED:-false}"
export SOUND_SOURCE="${SOUND_SOURCE:-rtsp}"
export SOUND_DB_THRESHOLD="${SOUND_DB_THRESHOLD:-10}"
export SOUND_COOLDOWN_SECONDS="${SOUND_COOLDOWN_SECONDS:-30}"
export SOUND_CALIBRATION_DURATION="${SOUND_CALIBRATION_DURATION:-120}"

exec /usr/bin/python3 -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --ws wsproto
