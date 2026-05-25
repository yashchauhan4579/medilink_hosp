"""Loud sound detection with adaptive baseline + YAMNet classification.

Captures audio continuously, learns ambient baseline, detects loud sounds
above threshold, classifies them with YAMNet, saves audio clips, and
triggers WhatsApp alerts.

Sources: MacBook mic (R&D) or RTSP camera audio (production on Jetson).
"""

import csv
import logging
import os
import time
import threading
import numpy as np
from collections import deque
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

SAMPLE_RATE = 16000
CHUNK_DURATION = 0.5  # seconds

# YAMNet alert categories — indices that indicate concerning sounds
ALERT_CATEGORIES = {
    "Screaming", "Shout", "Yell", "Scream", "Speech",
    "Glass", "Shatter", "Crash", "Bang", "Slam", "Explosion",
    "Alarm", "Siren", "Fire alarm", "Smoke detector",
    "Gunshot", "Gunfire",
    "Fighting", "Slap", "Whack",
    "Breaking", "Smash",
    "Emergency vehicle",
}


class SoundDetector:
    def __init__(
        self,
        source="mic",
        rtsp_url=None,
        db_threshold=15.0,
        cooldown_seconds=30,
        calibration_duration=120,
        model_path=None,
        class_map_path=None,
        clips_dir=None,
    ):
        self.source = source
        self.rtsp_url = rtsp_url
        self.db_threshold = db_threshold
        self.cooldown_seconds = cooldown_seconds
        self.calibration_duration = calibration_duration

        # Paths
        from app.config import DATA_DIR, MODELS_DIR
        base = Path(__file__).resolve().parent.parent.parent
        self.model_path = model_path or str(MODELS_DIR / "yamnet.tflite")
        self.class_map_path = class_map_path or str(MODELS_DIR / "yamnet_class_map.csv")
        self.clips_dir = Path(clips_dir or str(DATA_DIR / "sound_clips"))
        self.clips_dir.mkdir(parents=True, exist_ok=True)

        # State
        self._running = False
        self._calibrating = False
        self._calibrated = False
        self._capture = None
        self._interpreter = None
        self._class_names = []

        # Baseline
        self.baseline_rms = 0.0
        self.baseline_db = -60.0
        self._calibration_samples = []
        self._calibration_start = 0

        # Audio ring buffer (stores last 10s for clip saving)
        self._ring_buffer = deque(maxlen=int(10 / CHUNK_DURATION))
        self._ring_lock = threading.Lock()

        # Video ring buffer (stores last ~10s of frames from pipeline)
        self._video_buffer = deque(maxlen=60)  # ~6 FPS * 10s
        self._video_lock = threading.Lock()

        # Cooldown
        self._last_alert_time = 0

        # YAMNet accumulator (needs ~1s of audio = 2 chunks)
        self._yamnet_buffer = []
        self._yamnet_samples_needed = SAMPLE_RATE  # 1 second

        # Adaptive baseline recalibration
        self._ambient_window = deque(maxlen=int(30 * 60 / CHUNK_DURATION))  # 30 min
        self._recalib_interval = 30 * 60  # 30 min
        self._last_recalib = 0

        # Alert callback (set externally for WhatsApp/DB integration)
        self.on_alert = None

    def _load_yamnet(self):
        """Load YAMNet TFLite model and class map."""
        try:
            from ai_edge_litert.interpreter import Interpreter
        except ImportError:
            try:
                from tflite_runtime.interpreter import Interpreter
            except ImportError:
                import tensorflow as tf
                Interpreter = tf.lite.Interpreter

        if not os.path.exists(self.model_path):
            logger.error(f"YAMNet model not found: {self.model_path}")
            return False

        self._interpreter = Interpreter(model_path=self.model_path)
        self._interpreter.allocate_tensors()

        input_details = self._interpreter.get_input_details()
        output_details = self._interpreter.get_output_details()
        logger.info(f"YAMNet loaded: input={input_details[0]['shape']}, outputs={len(output_details)}")

        # Load class names
        if os.path.exists(self.class_map_path):
            with open(self.class_map_path) as f:
                reader = csv.DictReader(f)
                self._class_names = [row["display_name"] for row in reader]
            logger.info(f"YAMNet class map: {len(self._class_names)} classes")
        else:
            logger.warning("YAMNet class map not found — classifications will be numeric")

        return True

    def start(self):
        """Start audio capture and begin calibration."""
        if not self._load_yamnet():
            logger.error("Cannot start sound detector — YAMNet failed to load")
            return False

        self._running = True
        self._calibrating = True
        self._calibrated = False
        self._calibration_samples = []
        self._calibration_start = time.time()

        # Create audio source
        from app.services.audio_capture import MicCapture, RTSPCapture

        if self.source == "rtsp" and self.rtsp_url:
            self._capture = RTSPCapture(self.rtsp_url, self._on_audio_chunk)
        else:
            self._capture = MicCapture(self._on_audio_chunk)

        self._capture.start()
        logger.info(
            f"Sound detector started (source={self.source}, "
            f"threshold={self.db_threshold}dB, "
            f"calibration={self.calibration_duration}s)"
        )
        return True

    def _start_without_capture(self):
        """Start calibration + monitoring without creating own audio source.
        Used when audio is fed externally (e.g. from FrameGrabber's GStreamer pipeline)."""
        if not self._load_yamnet():
            logger.error("Cannot start sound detector — YAMNet failed to load")
            return False

        self._running = True
        self._calibrating = True
        self._calibrated = False
        self._calibration_samples = []
        self._calibration_start = time.time()

        logger.info(
            f"Sound detector started (source=external, "
            f"threshold={self.db_threshold}dB, "
            f"calibration={self.calibration_duration}s)"
        )
        return True

    def push_frame(self, cam_id: int, frame):
        """Called from pipeline._process_frame() — must be fast, never block."""
        with self._video_lock:
            self._video_buffer.append({
                "frame": frame.copy(),
                "time": time.time(),
            })

    def stop(self):
        self._running = False
        if self._capture:
            self._capture.stop()
            self._capture = None
        logger.info("Sound detector stopped")

    def _rms_to_db(self, rms):
        if rms < 1e-10:
            return -100.0
        return 20 * np.log10(rms)

    def _on_audio_chunk(self, chunk: np.ndarray):
        """Called by audio capture with each chunk (16kHz mono float32)."""
        if not self._running:
            return

        rms = np.sqrt(np.mean(chunk ** 2))
        db = self._rms_to_db(rms)

        # Store in ring buffer
        with self._ring_lock:
            self._ring_buffer.append({
                "audio": chunk.copy(),
                "rms": rms,
                "db": db,
                "time": time.time(),
            })

        if self._calibrating:
            self._calibration_samples.append(rms)
            elapsed = time.time() - self._calibration_start
            # Log progress every 10s
            if len(self._calibration_samples) % int(10 / CHUNK_DURATION) == 0:
                logger.info(
                    f"Calibrating... {elapsed:.0f}/{self.calibration_duration}s "
                    f"(samples={len(self._calibration_samples)}, current_db={db:.1f})"
                )
            if elapsed >= self.calibration_duration:
                self._finish_calibration()
            return

        if not self._calibrated:
            return

        # Store for adaptive baseline (only non-spike samples)
        spike_db = self.baseline_db + self.db_threshold
        if db < spike_db:
            self._ambient_window.append(rms)

        # Check for loud sound
        db_above = db - self.baseline_db
        if db_above >= self.db_threshold:
            self._on_loud_sound(chunk, db, db_above)

        # Periodic recalibration
        if time.time() - self._last_recalib > self._recalib_interval:
            self._recalibrate()

    def _finish_calibration(self):
        """Compute baseline from calibration samples."""
        self._calibrating = False
        if not self._calibration_samples:
            logger.error("No calibration samples collected!")
            return

        rms_values = np.array(self._calibration_samples)
        # Use median to be robust against outliers
        self.baseline_rms = float(np.median(rms_values))
        self.baseline_db = self._rms_to_db(self.baseline_rms)

        p95_rms = float(np.percentile(rms_values, 95))
        p95_db = self._rms_to_db(p95_rms)

        self._calibrated = True
        self._last_recalib = time.time()

        logger.info(
            f"=== CALIBRATION COMPLETE ===\n"
            f"  Samples: {len(self._calibration_samples)}\n"
            f"  Baseline RMS: {self.baseline_rms:.6f}\n"
            f"  Baseline dB: {self.baseline_db:.1f}\n"
            f"  95th percentile dB: {p95_db:.1f}\n"
            f"  Alert threshold: {self.baseline_db + self.db_threshold:.1f} dB "
            f"(baseline + {self.db_threshold})\n"
            f"  Monitoring started..."
        )

    def _recalibrate(self):
        """Update baseline from recent ambient samples."""
        if len(self._ambient_window) < 60:  # need at least 30s
            return
        rms_values = np.array(list(self._ambient_window))
        new_rms = float(np.median(rms_values))
        new_db = self._rms_to_db(new_rms)
        old_db = self.baseline_db

        self.baseline_rms = new_rms
        self.baseline_db = new_db
        self._last_recalib = time.time()

        if abs(new_db - old_db) > 1.0:
            logger.info(
                f"Baseline recalibrated: {old_db:.1f}dB → {new_db:.1f}dB "
                f"(threshold now {new_db + self.db_threshold:.1f}dB)"
            )

    def _on_loud_sound(self, chunk, db, db_above):
        """Handle loud sound detection."""
        now = time.time()
        if now - self._last_alert_time < self.cooldown_seconds:
            return

        # Accumulate audio for YAMNet (needs ~1s)
        self._yamnet_buffer.append(chunk)
        total_samples = sum(len(c) for c in self._yamnet_buffer)

        if total_samples < self._yamnet_samples_needed:
            return  # wait for more audio

        # Classify with YAMNet
        audio_1s = np.concatenate(self._yamnet_buffer)[:self._yamnet_samples_needed]
        self._yamnet_buffer = []

        categories = self._classify(audio_1s)
        top_category = categories[0] if categories else ("Unknown", 0.0)

        # Check if it's an alert-worthy category
        is_alert_category = any(
            alert_cat.lower() in top_category[0].lower()
            for alert_cat in ALERT_CATEGORIES
        )

        # Log all detections
        cats_str = ", ".join(f"{name}({score:.2f})" for name, score in categories[:5])
        logger.info(
            f"LOUD SOUND: +{db_above:.1f}dB above baseline | "
            f"Level: {db:.1f}dB | Categories: {cats_str}"
        )

        # Only alert on alert-worthy categories with sufficient confidence
        if not is_alert_category or top_category[1] < 0.05:
            logger.info(
                f"  → Skipped (category={top_category[0]}, "
                f"conf={top_category[1]:.2f}, alert={is_alert_category})"
            )
            return

        self._last_alert_time = now

        # Save audio clip (10s: 5s before + 5s after)
        clip_path = self._save_clip(top_category[0])

        alert_data = {
            "type": "loud_sound",
            "db_level": round(db, 1),
            "db_above_baseline": round(db_above, 1),
            "category": top_category[0],
            "confidence": round(top_category[1], 3),
            "top_categories": [(name, round(score, 3)) for name, score in categories[:5]],
            "clip_path": clip_path,
            "timestamp": datetime.now().isoformat(),
        }

        logger.warning(
            f"🔊 SOUND ALERT: {top_category[0]} "
            f"(+{db_above:.1f}dB, conf={top_category[1]:.2f}) "
            f"clip={clip_path}"
        )

        if self.on_alert:
            try:
                self.on_alert(alert_data)
            except Exception as e:
                logger.error(f"Alert callback error: {e}")

    def _classify(self, audio):
        """Run YAMNet on 1s of 16kHz mono float32 audio. Returns [(name, score), ...]."""
        if self._interpreter is None:
            return [("Unknown", 0.0)]

        try:
            input_details = self._interpreter.get_input_details()
            output_details = self._interpreter.get_output_details()

            # YAMNet expects float32 waveform
            waveform = audio.astype(np.float32)

            # Resize to expected input shape
            expected_len = input_details[0]["shape"][-1]
            if len(waveform) > expected_len:
                waveform = waveform[:expected_len]
            elif len(waveform) < expected_len:
                waveform = np.pad(waveform, (0, expected_len - len(waveform)))

            waveform = waveform.reshape(input_details[0]["shape"])

            self._interpreter.set_tensor(input_details[0]["index"], waveform)
            self._interpreter.invoke()

            scores = self._interpreter.get_tensor(output_details[0]["index"])[0]

            top_indices = np.argsort(scores)[::-1][:10]
            results = []
            for idx in top_indices:
                name = self._class_names[idx] if idx < len(self._class_names) else f"Class_{idx}"
                results.append((name, float(scores[idx])))

            return results

        except Exception as e:
            logger.error(f"YAMNet classification error: {e}")
            return [("Unknown", 0.0)]

    def _save_clip(self, category):
        """Save clip — WAV (mic mode) or MP4 with audio+video (RTSP mode)."""
        try:
            from scipy.io import wavfile

            with self._ring_lock:
                audio_entries = list(self._ring_buffer)
            with self._video_lock:
                video_entries = list(self._video_buffer)

            if not audio_entries:
                return None

            audio_chunks = [e["audio"] for e in audio_entries]
            audio = np.concatenate(audio_chunks)
            audio_int16 = (audio * 32767).astype(np.int16)

            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            safe_cat = category.replace(" ", "_").replace(",", "")[:30]

            # RTSP mode with video frames → save MP4 with audio + video
            if self.source == "rtsp" and len(video_entries) >= 3:
                return self._save_av_clip(audio_int16, audio_entries, video_entries, ts, safe_cat)

            # Mic mode or no video → save audio-only WAV
            filename = f"sound_{ts}_{safe_cat}.wav"
            filepath = str(self.clips_dir / filename)
            wavfile.write(filepath, SAMPLE_RATE, audio_int16)
            logger.info(f"Audio clip saved: {filepath} ({len(audio)/SAMPLE_RATE:.1f}s)")
            return filepath

        except Exception as e:
            logger.error(f"Failed to save clip: {e}")
            return None

    def _save_av_clip(self, audio_int16, audio_entries, video_entries, ts, safe_cat):
        """Save MP4 clip with synchronized audio + video from RTSP."""
        import subprocess
        import tempfile
        import shutil
        import cv2
        from scipy.io import wavfile

        tmpdir = tempfile.mkdtemp(prefix="sound_clip_")
        try:
            # Time window from audio buffer
            t_start = audio_entries[0]["time"]
            t_end = audio_entries[-1]["time"]

            # Filter video frames within audio time window
            frames = [e for e in video_entries if t_start <= e["time"] <= t_end]
            if len(frames) < 2:
                frames = video_entries  # fallback: use all frames

            # Write video frames as JPEGs
            for i, entry in enumerate(frames):
                frame = entry["frame"]
                cv2.imwrite(os.path.join(tmpdir, f"frame_{i:04d}.jpg"), frame)

            # Calculate FPS from actual frame timestamps
            time_span = frames[-1]["time"] - frames[0]["time"]
            fps = max(2, len(frames) / time_span) if time_span > 0 else 6

            # Write audio as temp WAV
            wav_path = os.path.join(tmpdir, "audio.wav")
            wavfile.write(wav_path, SAMPLE_RATE, audio_int16)

            # Mux with ffmpeg
            filename = f"sound_{ts}_{safe_cat}.mp4"
            filepath = str(self.clips_dir / filename)

            subprocess.run([
                "ffmpeg", "-y",
                "-framerate", str(round(fps, 1)),
                "-i", os.path.join(tmpdir, "frame_%04d.jpg"),
                "-i", wav_path,
                "-c:v", "libx264", "-pix_fmt", "yuv420p",
                "-c:a", "aac", "-b:a", "64k",
                "-movflags", "+faststart",
                "-shortest",
                filepath,
            ], capture_output=True, timeout=30)

            logger.info(f"A/V clip saved: {filepath} ({len(frames)} frames, {len(audio_int16)/SAMPLE_RATE:.1f}s audio)")
            return filepath

        except Exception as e:
            logger.error(f"Failed to save A/V clip: {e}")
            return None
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def get_status(self):
        """Return current detector status for API/dashboard."""
        return {
            "running": self._running,
            "calibrating": self._calibrating,
            "calibrated": self._calibrated,
            "source": self.source,
            "baseline_db": round(self.baseline_db, 1) if self._calibrated else None,
            "threshold_db": round(self.baseline_db + self.db_threshold, 1) if self._calibrated else None,
            "db_above_threshold": self.db_threshold,
            "cooldown_seconds": self.cooldown_seconds,
        }
