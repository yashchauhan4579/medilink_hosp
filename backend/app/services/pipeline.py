import asyncio
import json
import time
import logging
import threading
import cv2
import numpy as np
from pathlib import Path
from typing import Optional

from app import database as db
from app.config import (
    MODEL_PATH, MODEL_PT_PATH,
    PERSON_MODEL_PATH, PERSON_MODEL_PT_PATH,
    INFERENCE_FPS, JPEG_QUALITY, STREAM_HEIGHT,
    GEMINI_API_KEYS, GEMINI_MODEL,
    SOUND_DETECTION_ENABLED, SOUND_SOURCE,
    SOUND_DB_THRESHOLD, SOUND_COOLDOWN_SECONDS, SOUND_CALIBRATION_DURATION,
    FIGHT_CAMERA_IDS,
)
from app.services.frame_grabber import FrameGrabber
from app.services.alert_engine import AlertEngine
from app.services.stream_manager import stream_manager
from app.services.fight_detector import FightDetector
from app.services.sound_detector import SoundDetector

logger = logging.getLogger(__name__)


def _count_in_roi(detections: list, roi_polygon: list, frame_w: int, frame_h: int) -> int:
    if not roi_polygon or len(roi_polygon) < 3:
        return len(detections)

    roi_pixels = np.array(
        [[pt[0] / 100.0 * frame_w, pt[1] / 100.0 * frame_h] for pt in roi_polygon],
        dtype=np.float32,
    )
    count = 0
    for det in detections:
        cx, cy = det["center"]
        if cv2.pointPolygonTest(roi_pixels, (cx, cy), False) >= 0:
            count += 1
    return count


def _draw_overlays(frame, detections, rois, frame_w, frame_h):
    annotated = frame.copy()

    # Draw ROI polygons
    for module, color in [("reception", (0, 255, 200)), ("crowd", (255, 200, 0))]:
        roi = rois.get(module)
        if roi and len(roi) >= 3:
            pts = np.array(
                [[int(p[0] / 100.0 * frame_w), int(p[1] / 100.0 * frame_h)] for p in roi],
                dtype=np.int32,
            )
            cv2.polylines(annotated, [pts], True, color, 2)
            overlay = annotated.copy()
            cv2.fillPoly(overlay, [pts], (*color, 40))
            cv2.addWeighted(overlay, 0.15, annotated, 0.85, 0, annotated)
            # Label
            cv2.putText(annotated, module.upper(), (pts[0][0], pts[0][1] - 10),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 2)

    # Draw detection boxes
    for det in detections:
        x1, y1, x2, y2 = [int(v) for v in det["bbox"]]
        conf = det["confidence"]
        cv2.rectangle(annotated, (x1, y1), (x2, y2), (0, 255, 0), 2)
        cv2.putText(annotated, f"{conf:.2f}", (x1, y1 - 5),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.4, (0, 255, 0), 1)

    return annotated


class PipelineManager:
    def __init__(self):
        self._grabbers: dict[int, FrameGrabber] = {}
        self._head_model = None
        self._person_model = None
        self._running = False
        self._task: Optional[asyncio.Task] = None
        self.alert_engine = AlertEngine(stream_manager)
        self._latest_jpeg: dict[int, bytes] = {}
        self._latest_jpeg_raw: dict[int, bytes] = {}  # raw feed (no overlays)
        self.fight_detector = FightDetector(
            api_keys=GEMINI_API_KEYS,
            model_name=GEMINI_MODEL,
            stream_manager=stream_manager,
        )
        self.sound_detector = None
        self._sound_camera_id = None

    def get_latest_jpeg(self, camera_id: int, raw: bool = False) -> Optional[bytes]:
        if raw:
            return self._latest_jpeg_raw.get(camera_id) or self._latest_jpeg.get(camera_id)
        return self._latest_jpeg.get(camera_id)

    def _load_model(self):
        from ultralytics import YOLO

        if self._head_model is None:
            head_path = MODEL_PATH if Path(MODEL_PATH).exists() else MODEL_PT_PATH
            logger.info(f"Loading head model from {head_path}")
            self._head_model = YOLO(head_path, task="detect")
            logger.info("Head model loaded")

        if self._person_model is None:
            person_path = PERSON_MODEL_PATH if Path(PERSON_MODEL_PATH).exists() else PERSON_MODEL_PT_PATH
            logger.info(f"Loading person model from {person_path}")
            self._person_model = YOLO(person_path, task="detect")
            logger.info("Person model loaded")

    def start_camera(self, camera_id: int, rtsp_url: str, audio_callback=None):
        if camera_id in self._grabbers:
            self.stop_camera(camera_id)
        grabber = FrameGrabber(camera_id, rtsp_url, audio_callback=audio_callback)
        grabber.start()
        self._grabbers[camera_id] = grabber
        # Register with fight detector
        camera = db.get_camera(camera_id)
        cam_name = camera["name"] if camera else f"Camera {camera_id}"
        self.fight_detector.register_camera(camera_id, cam_name)
        logger.info(f"Pipeline: camera {camera_id} started")

    def stop_camera(self, camera_id: int):
        grabber = self._grabbers.pop(camera_id, None)
        if grabber:
            grabber.stop()
        self.alert_engine.reset_camera(camera_id)
        self.fight_detector.unregister_camera(camera_id)
        logger.info(f"Pipeline: camera {camera_id} stopped")

    def restart_camera(self, camera_id: int, rtsp_url: str):
        self.stop_camera(camera_id)
        self.start_camera(camera_id, rtsp_url)

    def get_camera_status(self, camera_id: int) -> dict:
        grabber = self._grabbers.get(camera_id)
        if not grabber:
            return {"status": "stopped", "connected": False}
        return {
            "status": "running",
            "connected": grabber.connected,
            "error": grabber.last_error,
        }

    def grab_snapshot(self, camera_id: int) -> Optional[np.ndarray]:
        grabber = self._grabbers.get(camera_id)
        if grabber:
            return grabber.grab_snapshot()
        return None

    def get_module_status(self) -> dict:
        cameras = db.get_all_cameras()
        cam_map = {c["id"]: c["name"] for c in cameras}
        result = {}

        # Reception and crowd: find cameras with module enabled AND ROI set
        for cam in cameras:
            if not cam["enabled"]:
                continue
            for module in ("reception", "crowd"):
                cfg = db.get_module_config(cam["id"], module)
                roi = db.get_roi(cam["id"], module)
                if cfg and cfg["enabled"] and roi and module not in result:
                    result[module] = {
                        "camera_id": cam["id"],
                        "camera_name": cam["name"],
                        "enabled": True,
                    }

        # Fight: pick the last registered camera (dedicated fight cam)
        fight_cams = list(self.fight_detector._camera_names.items())
        if fight_cams:
            cam_id, cam_name = fight_cams[-1]
            result["fight"] = {
                "camera_id": cam_id,
                "camera_name": cam_name,
                "enabled": self.fight_detector.is_enabled(),
            }

        # Sound — show panel even when detector is disabled (feed only)
        if self._sound_camera_id:
            if self.sound_detector:
                status = self.sound_detector.get_status()
                result["loud_sound"] = {
                    "camera_id": self._sound_camera_id,
                    "camera_name": cam_map.get(self._sound_camera_id, "Unknown"),
                    "enabled": True,
                    **status,
                }
            else:
                result["loud_sound"] = {
                    "camera_id": self._sound_camera_id,
                    "camera_name": cam_map.get(self._sound_camera_id, "Unknown"),
                    "enabled": False,
                }

        return result

    async def start(self):
        try:
            self._load_model()
        except Exception as e:
            logger.warning(f"Model not loaded yet: {e}. Inference will start when model is available.")
        self._running = True
        self.alert_engine.set_loop(asyncio.get_event_loop())

        # Create sound detector first (needed for audio callback wiring)
        if SOUND_DETECTION_ENABLED:
            self.sound_detector = SoundDetector(
                source=SOUND_SOURCE,
                rtsp_url=None,  # audio comes from FrameGrabber, not separate connection
                db_threshold=SOUND_DB_THRESHOLD,
                cooldown_seconds=SOUND_COOLDOWN_SECONDS,
                calibration_duration=SOUND_CALIBRATION_DURATION,
            )
            self.sound_detector.on_alert = self._on_sound_alert

        # Start grabbers for all enabled cameras
        cameras = db.get_all_cameras()
        audio_cam_started = False
        for cam in cameras:
            if cam["enabled"]:
                # Always track the first enabled camera for sound panel feed
                if self._sound_camera_id is None:
                    self._sound_camera_id = cam["id"]
                # Wire audio from first camera to sound detector (RTSP mode only)
                audio_cb = None
                if (SOUND_DETECTION_ENABLED and SOUND_SOURCE == "rtsp"
                        and self.sound_detector and not audio_cam_started):
                    audio_cb = self.sound_detector._on_audio_chunk
                    audio_cam_started = True
                    self._sound_camera_id = cam["id"]
                    logger.info(f"Sound detector: audio from camera {cam['id']} ({cam['name']})")
                self.start_camera(cam["id"], cam["rtsp_url"], audio_callback=audio_cb)

        self._task = asyncio.create_task(self._inference_loop())
        self.fight_detector.set_loop(asyncio.get_event_loop())
        self.fight_detector.start()

        # Start sound detector (loads YAMNet, begins calibration)
        if self.sound_detector:
            if SOUND_SOURCE == "rtsp" and audio_cam_started:
                # Audio already flowing from FrameGrabber — just load YAMNet and start calibration
                self.sound_detector._start_without_capture()
            else:
                self.sound_detector.start()

        logger.info("Pipeline manager started")

    async def stop(self):
        self._running = False
        self.fight_detector.stop()
        if self.sound_detector:
            self.sound_detector.stop()
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        for cid in list(self._grabbers.keys()):
            self.stop_camera(cid)
        logger.info("Pipeline manager stopped")

    async def _inference_loop(self):
        fps = INFERENCE_FPS
        target_interval = 1.0 / fps
        consecutive_errors = 0

        while self._running:
            if self._head_model is None or self._person_model is None:
                try:
                    self._load_model()
                except Exception:
                    await asyncio.sleep(5)
                    continue

            loop_start = time.monotonic()

            for cam_id, grabber in list(self._grabbers.items()):
                frame = grabber.grab()
                if frame is None:
                    continue

                try:
                    await self._process_frame(cam_id, frame, grabber)
                    consecutive_errors = 0
                except Exception as e:
                    consecutive_errors += 1
                    logger.error(f"Camera {cam_id} inference error: {e}", exc_info=True)
                    if consecutive_errors >= 50:
                        logger.warning("Too many consecutive errors, reloading models...")
                        self._head_model = None
                        self._person_model = None
                        consecutive_errors = 0
                        break

            elapsed = time.monotonic() - loop_start
            sleep_time = target_interval - elapsed
            if sleep_time > 0:
                await asyncio.sleep(sleep_time)
            else:
                await asyncio.sleep(0.001)  # yield to event loop

    def _on_sound_alert(self, alert_data):
        """Called by SoundDetector when a loud sound is detected."""
        from app.services.whatsapp import send_whatsapp_alert
        import os

        cam_id = self._sound_camera_id or 0
        clip_path_full = alert_data.get("clip_path")
        clip_filename = os.path.basename(clip_path_full) if clip_path_full else None
        alert = db.create_alert(
            cam_id,
            "loud_sound",
            f"Loud sound: {alert_data['category']} (+{alert_data['db_above_baseline']}dB)",
            head_count=0,
            snapshot_path=None,
            clip_path=clip_filename,
        )
        logger.info(f"Sound alert created: id={alert['id']}")

        # Send WhatsApp with clip
        clip_path = alert_data.get("clip_path")
        if clip_path:
            cat = alert_data["category"]
            db_above = alert_data["db_above_baseline"]
            wa_msg = (
                f"🔊 *LOUD SOUND ALERT*\n\n"
                f"⚠️ {cat} (+{db_above}dB above baseline)\n"
                f"🕐 Time: {alert_data['timestamp']}"
            )

            def _send():
                result = send_whatsapp_alert(wa_msg, clip_path)
                wa_status = result.get("status", "error")
                db.update_alert_whatsapp_status(alert["id"], wa_status)

            threading.Thread(target=_send, daemon=True).start()

        # Broadcast to dashboard
        loop = asyncio.get_event_loop()
        if loop:
            asyncio.run_coroutine_threadsafe(
                stream_manager.broadcast_alert(alert), loop
            )

    async def _process_frame(self, cam_id: int, frame: np.ndarray, grabber: FrameGrabber):
        camera = db.get_camera(cam_id)
        if not camera:
            return

        h, w = frame.shape[:2]

        # Get configs for both modules
        cfg_reception = db.get_module_config(cam_id, "reception")
        cfg_crowd = db.get_module_config(cam_id, "crowd")

        # Get ROIs
        roi_reception_data = db.get_roi(cam_id, "reception")
        roi_crowd_data = db.get_roi(cam_id, "crowd")
        roi_reception = roi_reception_data["polygon"] if roi_reception_data else None
        roi_crowd = roi_crowd_data["polygon"] if roi_crowd_data else None

        rois = {}
        if roi_reception:
            rois["reception"] = roi_reception
        if roi_crowd:
            rois["crowd"] = roi_crowd

        all_detections = []
        heads_reception = 0
        heads_crowd = 0

        # --- Person model for RECEPTION (detects full body from overhead) ---
        if cfg_reception and cfg_reception["enabled"] and roi_reception:
            conf_r = cfg_reception["confidence_threshold"]
            results_person = self._person_model.predict(
                frame, imgsz=640, conf=conf_r, classes=[0], verbose=False, device=0
            )
            person_dets = []
            for box in results_person[0].boxes:
                x1, y1, x2, y2 = box.xyxy[0].tolist()
                c = box.conf[0].item()
                cx, cy = (x1 + x2) / 2, (y1 + y2) / 2
                person_dets.append({
                    "bbox": [x1, y1, x2, y2],
                    "center": [cx, cy],
                    "confidence": round(c, 3),
                })
            all_detections.extend(person_dets)
            heads_reception = _count_in_roi(person_dets, roi_reception, w, h)

        # --- Head model for CROWD (detects heads for counting) ---
        if cfg_crowd and cfg_crowd["enabled"] and roi_crowd:
            conf_c = cfg_crowd["confidence_threshold"]
            results_head = self._head_model.predict(
                frame, imgsz=640, conf=conf_c, verbose=False, device=0
            )
            head_dets = []
            for box in results_head[0].boxes:
                x1, y1, x2, y2 = box.xyxy[0].tolist()
                c = box.conf[0].item()
                cx, cy = (x1 + x2) / 2, (y1 + y2) / 2
                head_dets.append({
                    "bbox": [x1, y1, x2, y2],
                    "center": [cx, cy],
                    "confidence": round(c, 3),
                })
            all_detections.extend(head_dets)
            heads_crowd = _count_in_roi(head_dets, roi_crowd, w, h)

        # For fight-only cameras (no reception/crowd enabled), skip YOLO — show raw feed
        is_fight_only = (FIGHT_CAMERA_IDS and cam_id in FIGHT_CAMERA_IDS
                         and not (cfg_reception and cfg_reception["enabled"] and roi_reception)
                         and not (cfg_crowd and cfg_crowd["enabled"] and roi_crowd))

        if not is_fight_only and not all_detections and not (cfg_reception and cfg_reception["enabled"]) and not (cfg_crowd and cfg_crowd["enabled"]):
            results_default = self._head_model.predict(
                frame, imgsz=640, conf=0.45, verbose=False, device=0
            )
            for box in results_default[0].boxes:
                x1, y1, x2, y2 = box.xyxy[0].tolist()
                c = box.conf[0].item()
                cx, cy = (x1 + x2) / 2, (y1 + y2) / 2
                all_detections.append({
                    "bbox": [x1, y1, x2, y2],
                    "center": [cx, cy],
                    "confidence": round(c, 3),
                })

        # Draw overlays (skip for fight-only cameras — raw feed)
        if is_fight_only:
            annotated = frame.copy()
        else:
            annotated = _draw_overlays(frame, all_detections, rois, w, h)

        # Run alert engine
        if cfg_reception and cfg_reception["enabled"] and roi_reception:
            self.alert_engine.update_reception(cam_id, heads_reception, annotated, camera["name"])

        if cfg_crowd and cfg_crowd["enabled"] and roi_crowd:
            self.alert_engine.update_crowd(cam_id, heads_crowd, annotated, camera["name"])

        # Resize for streaming
        if h > STREAM_HEIGHT:
            scale = STREAM_HEIGHT / h
            annotated = cv2.resize(annotated, (int(w * scale), STREAM_HEIGHT))

        # Encode JPEG and store for MJPEG streaming
        _, jpeg_buf = cv2.imencode('.jpg', annotated, [cv2.IMWRITE_JPEG_QUALITY, JPEG_QUALITY])
        self._latest_jpeg[cam_id] = jpeg_buf.tobytes()

        # Store raw feed (no overlays) for sound panel camera
        if cam_id == self._sound_camera_id:
            raw_frame = frame.copy()
            if h > STREAM_HEIGHT:
                scale = STREAM_HEIGHT / h
                raw_frame = cv2.resize(raw_frame, (int(w * scale), STREAM_HEIGHT))
            _, raw_buf = cv2.imencode('.jpg', raw_frame, [cv2.IMWRITE_JPEG_QUALITY, JPEG_QUALITY])
            self._latest_jpeg_raw[cam_id] = raw_buf.tobytes()

        # Push frame to fight detector (non-blocking)
        self.fight_detector.push_frame(cam_id, frame)

        # Push frame to sound detector (only from the sound camera)
        if self.sound_detector and cam_id == self._sound_camera_id:
            self.sound_detector.push_frame(cam_id, frame)

        # Broadcast metadata as text JSON via WebSocket
        meta = {
            "camera_id": cam_id,
            "detections": len(all_detections),
            "reception_heads": heads_reception,
            "crowd_heads": heads_crowd,
            "timestamp": time.time(),
        }
        # Add fight detector status for this camera
        if cam_id in self.fight_detector._buffers:
            meta["fight_status"] = "active" if self.fight_detector.is_enabled() else "disabled"
            meta["fight_cooldown"] = self.fight_detector._is_cooldown(cam_id)
        # Add sound detector status
        if self.sound_detector and cam_id == self._sound_camera_id:
            meta["sound"] = self.sound_detector.get_status()
        await stream_manager.broadcast_meta(cam_id, meta)


pipeline_manager = PipelineManager()
