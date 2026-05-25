import cv2
import threading
import time
import logging
import numpy as np
from typing import Optional, Callable

logger = logging.getLogger(__name__)


class FrameGrabber:
    """Grabs video frames from RTSP. Optionally extracts audio via GStreamer
    from the same single RTSP connection (avoids camera connection limits)."""

    def __init__(self, camera_id: int, rtsp_url: str, audio_callback: Optional[Callable] = None):
        self.camera_id = camera_id
        self.rtsp_url = rtsp_url
        self.latest_frame: Optional[np.ndarray] = None
        self._lock = threading.Lock()
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self.connected = False
        self.last_error: Optional[str] = None
        self._cap: Optional[cv2.VideoCapture] = None

        # Audio callback — if set, use GStreamer for video+audio from single connection
        self._audio_callback = audio_callback
        self._gst_pipeline = None

    def _open_capture(self) -> Optional[cv2.VideoCapture]:
        cap = cv2.VideoCapture(self.rtsp_url, cv2.CAP_FFMPEG)
        if not cap.isOpened():
            # Try with GStreamer
            cap = cv2.VideoCapture(self.rtsp_url)
        if cap.isOpened():
            cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
            return cap
        return None

    # --- cv2 mode (no audio, original behavior) ---

    def _run_cv2(self):
        reconnect_delay = 2
        while self._running:
            self._cap = self._open_capture()
            if self._cap is None:
                self.connected = False
                self.last_error = f"Cannot open {self.rtsp_url}"
                logger.warning(f"Camera {self.camera_id}: {self.last_error}")
                time.sleep(reconnect_delay)
                reconnect_delay = min(reconnect_delay * 2, 30)
                continue

            reconnect_delay = 2
            self.connected = True
            self.last_error = None
            logger.info(f"Camera {self.camera_id}: connected to {self.rtsp_url}")

            while self._running:
                ret, frame = self._cap.read()
                if not ret:
                    self.connected = False
                    self.last_error = "Frame read failed"
                    logger.warning(f"Camera {self.camera_id}: frame read failed, reconnecting...")
                    break
                with self._lock:
                    self.latest_frame = frame

            if self._cap:
                self._cap.release()
                self._cap = None

            if self._running:
                time.sleep(reconnect_delay)

    # --- GStreamer mode (video + audio from single RTSP connection) ---

    def _run_gstreamer(self):
        import gi
        gi.require_version('Gst', '1.0')
        from gi.repository import Gst, GLib
        Gst.init(None)

        reconnect_delay = 2
        while self._running:
            try:
                pipe_str = (
                    f'rtspsrc location={self.rtsp_url} protocols=tcp latency=200 name=src '
                    'src. ! application/x-rtp,media=video ! rtph265depay ! h265parse ! '
                    'nvv4l2decoder ! nvvidconv ! video/x-raw,format=BGRx ! '
                    'videoconvert ! video/x-raw,format=BGR ! '
                    'appsink name=vsink emit-signals=true max-buffers=1 drop=true sync=false '
                    'src. ! application/x-rtp,media=audio ! rtppcmadepay ! alawdec ! '
                    'audioconvert ! audioresample ! audio/x-raw,rate=16000,channels=1,format=S16LE ! '
                    'appsink name=asink emit-signals=true max-buffers=20 drop=false sync=false'
                )

                self._gst_pipeline = Gst.parse_launch(pipe_str)
                vsink = self._gst_pipeline.get_by_name('vsink')
                asink = self._gst_pipeline.get_by_name('asink')

                def on_video(sink):
                    sample = sink.emit('pull-sample')
                    if sample and self._running:
                        buf = sample.get_buffer()
                        caps = sample.get_caps()
                        s = caps.get_structure(0)
                        w = s.get_value('width')
                        h = s.get_value('height')
                        success, mapinfo = buf.map(Gst.MapFlags.READ)
                        if success:
                            frame = np.ndarray((h, w, 3), dtype=np.uint8, buffer=mapinfo.data).copy()
                            buf.unmap(mapinfo)
                            with self._lock:
                                self.latest_frame = frame
                    return Gst.FlowReturn.OK

                def on_audio(sink):
                    sample = sink.emit('pull-sample')
                    if sample and self._running and self._audio_callback:
                        buf = sample.get_buffer()
                        success, mapinfo = buf.map(Gst.MapFlags.READ)
                        if success:
                            audio = np.frombuffer(mapinfo.data, dtype=np.int16).astype(np.float32) / 32768.0
                            buf.unmap(mapinfo)
                            try:
                                self._audio_callback(audio)
                            except Exception as e:
                                logger.error(f"Camera {self.camera_id}: audio callback error: {e}")
                    return Gst.FlowReturn.OK

                vsink.connect('new-sample', on_video)
                asink.connect('new-sample', on_audio)

                self._gst_pipeline.set_state(Gst.State.PLAYING)
                bus = self._gst_pipeline.get_bus()

                reconnect_delay = 2
                self.connected = True
                self.last_error = None
                logger.info(f"Camera {self.camera_id}: GStreamer connected (video+audio) to {self.rtsp_url}")

                while self._running:
                    msg = bus.timed_pop_filtered(
                        1 * Gst.SECOND,
                        Gst.MessageType.ERROR | Gst.MessageType.EOS,
                    )
                    if msg:
                        if msg.type == Gst.MessageType.ERROR:
                            err, debug = msg.parse_error()
                            self.last_error = err.message
                            logger.warning(f"Camera {self.camera_id}: GStreamer error: {err.message}")
                        break

            except Exception as e:
                self.last_error = str(e)
                logger.error(f"Camera {self.camera_id}: GStreamer exception: {e}")
            finally:
                self.connected = False
                if self._gst_pipeline:
                    self._gst_pipeline.set_state(Gst.State.NULL)
                    self._gst_pipeline = None

            if self._running:
                logger.info(f"Camera {self.camera_id}: reconnecting in {reconnect_delay}s...")
                time.sleep(reconnect_delay)
                reconnect_delay = min(reconnect_delay * 2, 30)

    def start(self):
        if self._running:
            return
        self._running = True

        if self._audio_callback:
            self._thread = threading.Thread(target=self._run_gstreamer, daemon=True)
            mode = "GStreamer (video+audio)"
        else:
            self._thread = threading.Thread(target=self._run_cv2, daemon=True)
            mode = "cv2 (video only)"

        self._thread.start()
        logger.info(f"Camera {self.camera_id}: frame grabber started [{mode}]")

    def stop(self):
        self._running = False
        if self._cap:
            self._cap.release()
        if self._gst_pipeline:
            try:
                import gi
                gi.require_version('Gst', '1.0')
                from gi.repository import Gst
                self._gst_pipeline.set_state(Gst.State.NULL)
            except Exception:
                pass
            self._gst_pipeline = None
        if self._thread:
            self._thread.join(timeout=5)
        self.connected = False
        logger.info(f"Camera {self.camera_id}: frame grabber stopped")

    def grab(self) -> Optional[np.ndarray]:
        with self._lock:
            frame = self.latest_frame
            self.latest_frame = None
            return frame

    def grab_snapshot(self) -> Optional[np.ndarray]:
        """Grab a single frame without consuming the latest."""
        with self._lock:
            return self.latest_frame.copy() if self.latest_frame is not None else None
