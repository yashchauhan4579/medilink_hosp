"""Audio capture abstraction — MacBook mic or RTSP stream audio.

Both sources yield audio chunks in the same format: 16kHz mono float32 numpy arrays.
"""

import logging
import subprocess
import threading
import numpy as np

logger = logging.getLogger(__name__)

SAMPLE_RATE = 16000
CHUNK_DURATION = 0.5  # seconds per chunk
CHUNK_SAMPLES = int(SAMPLE_RATE * CHUNK_DURATION)


class MicCapture:
    """Capture audio from MacBook microphone via sounddevice."""

    def __init__(self, callback):
        """callback(audio_chunk: np.ndarray) called with each chunk (16kHz mono float32)."""
        self._callback = callback
        self._running = False
        self._stream = None

    def start(self):
        import sounddevice as sd
        self._running = True
        self._stream = sd.InputStream(
            samplerate=SAMPLE_RATE,
            channels=1,
            dtype="float32",
            blocksize=CHUNK_SAMPLES,
            callback=self._audio_callback,
        )
        self._stream.start()
        logger.info(f"MicCapture started (rate={SAMPLE_RATE}, chunk={CHUNK_DURATION}s)")

    def _audio_callback(self, indata, frames, time_info, status):
        if status:
            logger.warning(f"Audio status: {status}")
        if self._running:
            self._callback(indata[:, 0].copy())

    def stop(self):
        self._running = False
        if self._stream:
            self._stream.stop()
            self._stream.close()
            self._stream = None
        logger.info("MicCapture stopped")


class RTSPCapture:
    """Extract audio from RTSP camera stream via ffmpeg subprocess."""

    def __init__(self, rtsp_url: str, callback):
        self._url = rtsp_url
        self._callback = callback
        self._running = False
        self._proc = None
        self._thread = None

    def start(self):
        self._running = True
        self._thread = threading.Thread(target=self._capture_loop, daemon=True)
        self._thread.start()
        logger.info(f"RTSPCapture started: {self._url}")

    def _capture_loop(self):
        bytes_per_chunk = CHUNK_SAMPLES * 2  # 16-bit PCM = 2 bytes/sample

        while self._running:
            try:
                self._proc = subprocess.Popen(
                    [
                        "ffmpeg", "-i", self._url,
                        "-vn",  # no video
                        "-acodec", "pcm_s16le",
                        "-ar", str(SAMPLE_RATE),
                        "-ac", "1",  # mono
                        "-f", "s16le",
                        "pipe:1",
                    ],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL,
                )

                while self._running:
                    raw = self._proc.stdout.read(bytes_per_chunk)
                    if not raw or len(raw) < bytes_per_chunk:
                        break
                    audio = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
                    self._callback(audio)

            except Exception as e:
                logger.error(f"RTSPCapture error: {e}")
            finally:
                if self._proc:
                    self._proc.kill()
                    self._proc = None

            if self._running:
                import time
                logger.warning("RTSP audio stream lost, reconnecting in 5s...")
                time.sleep(5)

    def stop(self):
        self._running = False
        if self._proc:
            self._proc.kill()
            self._proc = None
        logger.info("RTSPCapture stopped")
