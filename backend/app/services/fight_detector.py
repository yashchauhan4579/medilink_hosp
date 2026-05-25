"""Fight detection using Gemini 2.5 Flash via OpenRouter or direct API.

Runs as a separate thread alongside the YOLO pipeline. Captures frames from
the pipeline's _process_frame(), buffers them, and sends 5 frames to Gemini
every ANALYSIS_INTERVAL seconds. On fight detection, triggers WhatsApp alert
via existing alert engine.

Supports OpenRouter (preferred) and direct Gemini API with key rotation.
"""

import cv2
import os
import time
import json
import base64
import logging
import threading
import re
import requests as http_requests
from io import BytesIO
from collections import deque
from datetime import datetime
from typing import Optional
from PIL import Image

from app import database as db
from app.config import (
    SNAPSHOTS_DIR, FIGHT_COOLDOWN_SECONDS, FIGHT_ANALYSIS_INTERVAL,
    OPENROUTER_API_KEY, OPENROUTER_MODEL, FIGHT_CAMERA_IDS,
)
from app.services.whatsapp import send_whatsapp_alert

logger = logging.getLogger(__name__)

ALERT_PROMPT = """Look at these {n} frames from camera "{camera_name}".
Is there any physical altercation, aggression, or unwanted physical contact between two or more people? This includes fighting, pushing, shoving, grabbing, slapping, pulling, wrestling, or any forceful physical interaction.

If YES respond: FIGHT: followed by a complete 2 sentence description of exactly what is happening, who is involved, and what the crowd is doing.
If NO respond: NORMAL

Be very sensitive — even someone touching another person's hands, grabbing an arm, light pushing, or any unwanted physical contact between people should be flagged. When in doubt, flag it.

Example: FIGHT: Two men are pushing and shoving each other near the corridor entrance while a third person tries to separate them. Other people nearby are watching nervously and backing away from the confrontation."""


def infer_type(description):
    desc = (description or "").lower()
    if any(w in desc for w in ["fight", "punch", "kick", "hit", "attack", "strike", "brawl", "wrestl", "slap"]):
        return "fighting"
    if any(w in desc for w in ["shov", "push", "aggress", "threaten", "confront", "intimidat", "grab", "pull", "touch", "hold"]):
        return "aggression"
    if any(w in desc for w in ["panic", "stampede", "flee", "running away", "scatter", "chaos"]):
        return "crowd_panic"
    if any(w in desc for w in ["fall", "ground", "down", "collapse", "lying", "knocked"]):
        return "person_down"
    if any(w in desc for w in ["vandal", "break", "smash", "destroy", "damage", "throw"]):
        return "vandalism"
    return "activity_attention"


class FightDetector:
    def __init__(self, api_keys: list, model_name: str = "gemini-2.5-flash", stream_manager=None):
        self.api_keys = [k.strip() for k in api_keys if k.strip()]
        self.model_name = model_name
        self.stream_manager = stream_manager
        self._loop = None

        # Per-camera state
        self._buffers: dict[int, deque] = {}
        self._buffer_locks: dict[int, threading.Lock] = {}
        self._cooldowns: dict[int, float] = {}
        self._cooldown_lock = threading.Lock()
        self._camera_names: dict[int, str] = {}

        # API backend
        self._use_openrouter = bool(OPENROUTER_API_KEY)
        self._models = []
        self._current_key = 0
        self._key_lock = threading.Lock()

        self._running = False
        self._threads: list[threading.Thread] = []

        if self._use_openrouter:
            logger.info(f"Fight detector: using OpenRouter ({OPENROUTER_MODEL})")
        elif self.api_keys:
            import google.generativeai as genai
            from google.api_core.exceptions import ResourceExhausted  # noqa: F811
            self._genai = genai
            self._ResourceExhausted = ResourceExhausted
            for i, key in enumerate(self.api_keys):
                genai.configure(api_key=key)
                model = genai.GenerativeModel(model_name)
                self._models.append((key, model))
                logger.info(f"Gemini key {i+1}/{len(self.api_keys)} initialized")
        else:
            logger.warning("No API keys configured — fight detection disabled")

    def set_loop(self, loop):
        self._loop = loop

    def is_enabled(self) -> bool:
        return self._use_openrouter or len(self._models) > 0

    def register_camera(self, camera_id: int, camera_name: str):
        if camera_id not in self._buffers:
            self._buffers[camera_id] = deque(maxlen=10)
            self._buffer_locks[camera_id] = threading.Lock()
            self._camera_names[camera_id] = camera_name
            logger.info(f"Fight detector: registered camera {camera_id} ({camera_name})")

    def unregister_camera(self, camera_id: int):
        self._buffers.pop(camera_id, None)
        self._buffer_locks.pop(camera_id, None)
        self._camera_names.pop(camera_id, None)
        with self._cooldown_lock:
            self._cooldowns.pop(camera_id, None)

    def push_frame(self, camera_id: int, frame):
        """Called from pipeline._process_frame() — must be fast, never block."""
        lock = self._buffer_locks.get(camera_id)
        if lock is None:
            return
        with lock:
            self._buffers[camera_id].append({
                "frame": frame.copy(),
                "timestamp": time.time(),
            })

    def start(self):
        if not self.is_enabled():
            return
        self._running = True
        t = threading.Thread(target=self._analysis_loop, daemon=True)
        t.start()
        self._threads.append(t)
        logger.info(f"Fight detector started (interval={FIGHT_ANALYSIS_INTERVAL}s, cooldown={FIGHT_COOLDOWN_SECONDS}s, keys={len(self._models)})")

    def stop(self):
        self._running = False

    def _is_cooldown(self, camera_id: int) -> bool:
        with self._cooldown_lock:
            return time.time() < self._cooldowns.get(camera_id, 0)

    def _set_cooldown(self, camera_id: int):
        with self._cooldown_lock:
            self._cooldowns[camera_id] = time.time() + FIGHT_COOLDOWN_SECONDS

    def _analysis_loop(self):
        time.sleep(10)  # let pipeline stabilize
        if not FIGHT_CAMERA_IDS:
            logger.info("Fight detector: no cameras configured, analysis disabled")
            return
        logger.info(f"Fight detector analysis loop started (cameras={FIGHT_CAMERA_IDS})")
        while self._running:
            for cam_id in list(self._buffers.keys()):
                if not self._running:
                    break
                # Skip cameras not in the allowed list
                if cam_id not in FIGHT_CAMERA_IDS:
                    continue
                if self._is_cooldown(cam_id):
                    continue
                try:
                    self._analyze_camera(cam_id)
                except Exception as e:
                    logger.error(f"Fight analysis error cam {cam_id}: {e}")
            time.sleep(FIGHT_ANALYSIS_INTERVAL)

    def _get_frames(self, camera_id: int):
        lock = self._buffer_locks.get(camera_id)
        if not lock:
            return None
        with lock:
            buf = list(self._buffers[camera_id])
        if len(buf) < 5:
            return None
        indices = [0, 2, 4, 6, 8] if len(buf) >= 9 else [i * (len(buf) - 1) // 4 for i in range(5)]
        return [buf[i] for i in indices if i < len(buf)]

    def _frame_to_pil(self, frame):
        h, w = frame.shape[:2]
        if w > 768:
            scale = 768 / w
            frame = cv2.resize(frame, (768, int(h * scale)))
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        return Image.fromarray(rgb)

    def _frame_to_base64(self, frame):
        """Convert frame to base64 JPEG for OpenRouter API."""
        h, w = frame.shape[:2]
        if w > 768:
            scale = 768 / w
            frame = cv2.resize(frame, (768, int(h * scale)))
        _, buf = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 70])
        return base64.b64encode(buf.tobytes()).decode('utf-8')

    def _call_openrouter(self, prompt, images):
        """Call OpenRouter API with base64 images."""
        content = []
        for img in images:
            b64 = self._frame_to_base64(img) if not isinstance(img, str) else img
            content.append({
                "type": "image_url",
                "image_url": {"url": f"data:image/jpeg;base64,{b64}"},
            })
        content.append({"type": "text", "text": prompt})

        try:
            resp = http_requests.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {OPENROUTER_API_KEY}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": OPENROUTER_MODEL,
                    "messages": [{"role": "user", "content": content}],
                    "temperature": 0.1,
                    "max_tokens": 500,
                },
                timeout=30,
            )
            if resp.status_code == 429:
                logger.warning("OpenRouter rate limited")
                return None
            resp.raise_for_status()
            data = resp.json()
            text = data["choices"][0]["message"]["content"]

            class _Resp:
                pass
            r = _Resp()
            r.text = text
            return r
        except Exception as e:
            logger.error(f"OpenRouter API error: {e}")
            return None

    def _call_gemini(self, content):
        """Call Gemini with automatic key rotation on 429."""
        with self._key_lock:
            start_key = self._current_key

        for attempt in range(len(self._models)):
            with self._key_lock:
                idx = self._current_key
            key, model = self._models[idx]
            try:
                response = model.generate_content(
                    content,
                    generation_config=self._genai.GenerationConfig(
                        temperature=0.1,
                        max_output_tokens=500,
                    ),
                )
                return response
            except self._ResourceExhausted:
                with self._key_lock:
                    self._current_key = (self._current_key + 1) % len(self._models)
                logger.warning(f"Gemini key {idx+1} rate limited, switching to key {self._current_key+1}")
            except Exception as e:
                logger.error(f"Gemini API error: {e}")
                return None

        logger.error("All Gemini keys exhausted")
        return None

    def _save_clip(self, camera_id: int, clip_path: str):
        """Save all buffered frames as a short H.264 MP4 clip for WhatsApp."""
        import subprocess
        import tempfile
        import shutil

        lock = self._buffer_locks.get(camera_id)
        if not lock:
            return
        with lock:
            buf = list(self._buffers[camera_id])
        if len(buf) < 3:
            return
        try:
            h, w = buf[0]["frame"].shape[:2]
            # Save annotated frames as temp JPEGs
            tmpdir = tempfile.mkdtemp(prefix="fight_")
            for i, entry in enumerate(buf):
                frame = entry["frame"].copy()
                cv2.rectangle(frame, (0, 0), (w - 1, h - 1), (0, 0, 255), 3)
                cv2.rectangle(frame, (0, 0), (w, 40), (0, 0, 200), -1)
                cv2.putText(frame, "FIGHT DETECTED", (10, 28),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 255, 255), 2)
                cv2.imwrite(os.path.join(tmpdir, f"frame_{i:03d}.jpg"), frame)

            # Encode H.264 with ffmpeg
            subprocess.run([
                "ffmpeg", "-y", "-framerate", "2",
                "-i", os.path.join(tmpdir, "frame_%03d.jpg"),
                "-c:v", "libx264", "-pix_fmt", "yuv420p",
                "-movflags", "+faststart", clip_path,
            ], capture_output=True, timeout=30)

            shutil.rmtree(tmpdir, ignore_errors=True)
            logger.info(f"Fight clip saved: {clip_path} ({len(buf)} frames)")
        except Exception as e:
            logger.error(f"Failed to save fight clip: {e}")

    def _analyze_camera(self, camera_id: int):
        frames = self._get_frames(camera_id)
        if not frames:
            return

        camera_name = self._camera_names.get(camera_id, f"Camera {camera_id}")
        prompt = ALERT_PROMPT.format(n=len(frames), camera_name=camera_name)

        if self._use_openrouter:
            raw_frames = [f["frame"] for f in frames]
            response = self._call_openrouter(prompt, raw_frames)
        else:
            images = [self._frame_to_pil(f["frame"]) for f in frames]
            response = self._call_gemini([prompt] + images)

        if response is None:
            return

        text = response.text.strip()
        logger.info(f"[{camera_name}] Gemini: {text[:100]}")

        if "FIGHT" not in text.upper()[:10]:
            return

        # Fight detected
        desc = text
        if ":" in text[:10]:
            desc = text.split(":", 1)[1].strip()
        elif "\n" in text:
            desc = text.split("\n", 1)[1].strip()
        if not desc or desc == text:
            desc = "Fight detected"

        if not desc.endswith("."):
            desc = f"Physical altercation detected at {camera_name}. {desc.rstrip()}..."

        alert_type = infer_type(desc)
        logger.warning(f"[{camera_name}] FIGHT ALERT: {alert_type} — {desc[:100]}")

        # Set cooldown FIRST
        self._set_cooldown(camera_id)

        ts = int(time.time())

        # Save best frame (for DB snapshot)
        best_frame = frames[len(frames) // 2]["frame"]
        snapshot_filename = f"{camera_id}_fight_{ts}.jpg"
        snapshot_path = str(SNAPSHOTS_DIR / snapshot_filename)
        cv2.imwrite(snapshot_path, best_frame)

        # Save clip from all buffered frames (for WhatsApp)
        clip_filename = f"{camera_id}_fight_{ts}.mp4"
        clip_path = str(SNAPSHOTS_DIR / clip_filename)
        self._save_clip(camera_id, clip_path)

        # Create alert in DB (reuse existing alerts table)
        alert = db.create_alert(
            camera_id, "fight",
            f"Fight detected: {desc[:200]}",
            head_count=0,
            snapshot_path=snapshot_filename,
            clip_path=clip_filename,
        )
        logger.info(f"Fight alert created: id={alert['id']}")

        # Fight alerts: WhatsApp NOT auto-sent — user sends manually from dashboard
        logger.info(f"Fight alert {alert['id']} created — WhatsApp pending manual send")

        # Save clip in background for local review (not sent to WhatsApp)
        threading.Thread(target=self._save_clip, args=(camera_id, clip_path), daemon=True).start()

        # Broadcast to dashboard
        if self._loop and self.stream_manager:
            import asyncio
            asyncio.run_coroutine_threadsafe(
                self.stream_manager.broadcast_alert(alert),
                self._loop,
            )
