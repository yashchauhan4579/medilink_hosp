# Medilink Hospital Monitor

AI-powered hospital surveillance system running on NVIDIA Jetson Orin Nano. Monitors camera feeds in real-time for reception absence, crowd buildup, fights, and loud sounds — sends WhatsApp alerts automatically.

## Features

- **Reception Monitoring** — Detects when no attendant is present at the reception desk
- **Crowd Detection** — Alerts when crowd count exceeds threshold in waiting areas
- **Fight Detection** — Uses Gemini/OpenRouter vision API to analyze suspicious activity
- **Sound Detection** — YAMNet-based audio classification for loud sounds (screaming, glass breaking, etc.)
- **WhatsApp Alerts** — Instant notifications with snapshots to designated phone numbers
- **Live Feed** — Real-time WebSocket video streaming with ROI overlay
- **Web Dashboard** — React frontend for camera management, alerts, and settings

## Tech Stack

- **Backend:** Python, FastAPI, Uvicorn, SQLite
- **Frontend:** React, TypeScript, Vite, Tailwind CSS
- **AI Models:** YOLOv8 (person/head detection via TensorRT), YAMNet (sound classification)
- **Hardware:** NVIDIA Jetson Orin Nano, IP cameras (RTSP)

## Setup

```bash
# 1. Clone
git clone https://github.com/yashchauhan4579/medilink_hosp.git
cd medilink_hosp

# 2. Configure environment
cp .env.example .env
# Edit .env with your API keys

# 3. Install backend dependencies
cd backend
pip install -r requirements.txt

# 4. Place model files in models/
#    - best_head.pt / best_head.engine (head detection)
#    - yolov8n.pt / yolov8n.engine (person detection)
#    - yamnet.tflite + yamnet_class_map.csv (sound classification)

# 5. Build frontend (optional — pre-built dist can be used)
cd ../frontend
npm install && npm run build

# 6. Run
cd ..
bash start.sh
```

The dashboard will be available at `http://<device-ip>:8000`.

## Project Structure

```
backend/
  app/
    config.py          — Environment config and paths
    database.py        — SQLite DB schema and queries
    main.py            — FastAPI app entry point
    models.py          — Pydantic request models
    routers/           — REST API endpoints (cameras, alerts, ROI, settings)
    services/          — Core logic (pipeline, detection, alerting)
    ws/                — WebSocket live feed
  scripts/             — Model conversion utilities
frontend/
  src/
    pages/             — Dashboard, Camera, Alerts, Settings pages
    components/        — LiveFeed, ROI drawer
    lib/               — API client, WebSocket helpers
start.sh               — Startup script with env config
```

## License

Proprietary — WiredLeap Technologies
