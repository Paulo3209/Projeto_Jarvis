"""
Camera Module - Webcam capture and video streaming for JARVIS.
Supports OpenCV for capture, with optional async interface.
"""
from __future__ import annotations
import asyncio
import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, AsyncGenerator, Callable, Any
import threading

import cv2
import numpy as np

logger = logging.getLogger(__name__)


@dataclass
class CameraConfig:
    """Camera configuration."""
    device_index: int = 0
    width: int = 1280
    height: int = 720
    fps: int = 30
    backend: int = cv2.CAP_DSHOW  # Windows DirectShow
    auto_exposure: bool = True
    exposure: float = -1  # -1 = auto
    brightness: float = -1
    contrast: float = -1
    saturation: float = -1


@dataclass
class CameraFrame:
    """Captured frame with metadata."""
    frame: np.ndarray
    timestamp: float
    frame_number: int
    width: int
    height: int


class CameraManager:
    """
    Manages webcam capture with OpenCV.
    Provides both sync and async interfaces.
    """

    def __init__(self, config: CameraConfig = None):
        self.config = config or CameraConfig()
        self._cap: Optional[cv2.VideoCapture] = None
        self._running = False
        self._frame_callback: Optional[Callable[[CameraFrame], None]] = None
        self._capture_thread: Optional[threading.Thread] = None
        self._frame_queue: asyncio.Queue = asyncio.Queue(maxsize=5)
        self._frame_count = 0
        self._last_frame: Optional[CameraFrame] = None
        self._lock = threading.Lock()

    def open(self) -> bool:
        """Open camera connection."""
        if self._cap is not None and self._cap.isOpened():
            logger.warning("Camera already open")
            return True

        try:
            self._cap = cv2.VideoCapture(self.config.device_index, self.config.backend)

            if not self._cap.isOpened():
                logger.error(f"Failed to open camera {self.config.device_index}")
                return False

            # Set properties
            self._cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.config.width)
            self._cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.config.height)
            self._cap.set(cv2.CAP_PROP_FPS, self.config.fps)

            if self.config.auto_exposure:
                self._cap.set(cv2.CAP_PROP_AUTO_EXPOSURE, 0.75)
            elif self.config.exposure >= 0:
                self._cap.set(cv2.CAP_PROP_AUTO_EXPOSURE, 0.25)
                self._cap.set(cv2.CAP_PROP_EXPOSURE, self.config.exposure)

            if self.config.brightness >= 0:
                self._cap.set(cv2.CAP_PROP_BRIGHTNESS, self.config.brightness)
            if self.config.contrast >= 0:
                self._cap.set(cv2.CAP_PROP_CONTRAST, self.config.contrast)
            if self.config.saturation >= 0:
                self._cap.set(cv2.CAP_PROP_SATURATION, self.config.saturation)

            # Verify actual settings
            actual_width = int(self._cap.get(cv2.CAP_PROP_FRAME_WIDTH))
            actual_height = int(self._cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
            actual_fps = self._cap.get(cv2.CAP_PROP_FPS)

            logger.info(f"Camera opened: {actual_width}x{actual_height} @ {actual_fps}fps")
            return True

        except Exception as e:
            logger.error(f"Error opening camera: {e}")
            self._cap = None
            return False

    def close(self) -> None:
        """Close camera connection."""
        self.stop_capture()

        if self._cap:
            self._cap.release()
            self._cap = None

        logger.info("Camera closed")

    def is_open(self) -> bool:
        """Check if camera is open."""
        return self._cap is not None and self._cap.isOpened()

    def capture_frame(self) -> Optional[CameraFrame]:
        """Capture a single frame synchronously."""
        if not self.is_open():
            if not self.open():
                return None

        ret, frame = self._cap.read()
        if not ret or frame is None:
            logger.error("Failed to capture frame")
            return None

        self._frame_count += 1
        camera_frame = CameraFrame(
            frame=frame,
            timestamp=time.time(),
            frame_number=self._frame_count,
            width=frame.shape[1],
            height=frame.shape[0]
        )
        self._last_frame = camera_frame
        return camera_frame

    def capture_to_file(self, path: str, format: str = "jpg") -> bool:
        """Capture a frame and save to file."""
        frame_data = self.capture_frame()
        if frame_data is None:
            return False

        try:
            # Ensure extension
            path = Path(path)
            if format.lower() in ("jpg", "jpeg"):
                path = path.with_suffix(".jpg")
                cv2.imwrite(str(path), frame_data.frame, [cv2.IMWRITE_JPEG_QUALITY, 90])
            elif format.lower() == "png":
                path = path.with_suffix(".png")
                cv2.imwrite(str(path), frame_data.frame, [cv2.IMWRITE_PNG_COMPRESSION, 3])
            else:
                path = path.with_suffix(f".{format}")
                cv2.imwrite(str(path), frame_data.frame)

            logger.info(f"Frame saved to {path}")
            return True
        except Exception as e:
            logger.error(f"Error saving frame: {e}")
            return False

    def start_capture(self, callback: Callable[[CameraFrame], None] = None) -> bool:
        """Start continuous capture in background thread."""
        if self._running:
            logger.warning("Capture already running")
            return True

        if not self.is_open():
            if not self.open():
                return False

        self._running = True
        self._frame_callback = callback

        def capture_loop():
            while self._running:
                ret, frame = self._cap.read()
                if not ret or frame is None:
                    time.sleep(0.01)
                    continue

                self._frame_count += 1
                camera_frame = CameraFrame(
                    frame=frame,
                    timestamp=time.time(),
                    frame_number=self._frame_count,
                    width=frame.shape[1],
                    height=frame.shape[0]
                )
                self._last_frame = camera_frame

                # Call sync callback
                if self._frame_callback:
                    try:
                        self._frame_callback(camera_frame)
                    except Exception as e:
                        logger.error(f"Frame callback error: {e}")

                # Put in async queue (non-blocking)
                try:
                    self._frame_queue.put_nowait(camera_frame)
                except asyncio.QueueFull:
                    # Drop oldest frame
                    try:
                        self._frame_queue.get_nowait()
                        self._frame_queue.put_nowait(camera_frame)
                    except Exception:
                        pass

        self._capture_thread = threading.Thread(target=capture_loop, daemon=True)
        self._capture_thread.start()
        logger.info("Continuous capture started")
        return True

    def stop_capture(self) -> None:
        """Stop continuous capture."""
        self._running = False
        if self._capture_thread and self._capture_thread.is_alive():
            self._capture_thread.join(timeout=2.0)
            self._capture_thread = None
        self._frame_callback = None
        logger.info("Continuous capture stopped")

    def get_last_frame(self) -> Optional[CameraFrame]:
        """Get the last captured frame."""
        return self._last_frame

    async def get_frame_async(self, timeout: float = 1.0) -> Optional[CameraFrame]:
        """Get next frame asynchronously."""
        if not self._running:
            if not self.start_capture():
                return None

        try:
            return await asyncio.wait_for(self._frame_queue.get(), timeout=timeout)
        except asyncio.TimeoutError:
            return None

    async def stream_frames(self, max_fps: float = 30) -> AsyncGenerator[CameraFrame, None]:
        """Async generator for streaming frames."""
        if not self._running:
            if not self.start_capture():
                return

        min_interval = 1.0 / max_fps
        last_yield = 0

        while self._running:
            frame = await self.get_frame_async(timeout=2.0)
            if frame is None:
                continue

            now = time.time()
            if now - last_yield >= min_interval:
                yield frame
                last_yield = now
            else:
                # Put back for next iteration
                try:
                    self._frame_queue.put_nowait(frame)
                except Exception:
                    pass
                await asyncio.sleep(min_interval - (now - last_yield))

    def list_cameras(self, max_test: int = 10) -> list[dict]:
        """List available cameras."""
        cameras = []
        for i in range(max_test):
            cap = cv2.VideoCapture(i, self.config.backend)
            if cap.isOpened():
                width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
                height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
                fps = cap.get(cv2.CAP_PROP_FPS)
                cameras.append({
                    "index": i,
                    "width": width,
                    "height": height,
                    "fps": fps
                })
                cap.release()
            else:
                cap.release()
        return cameras

    def get_properties(self) -> dict:
        """Get current camera properties."""
        if not self.is_open():
            return {}

        props = {}
        prop_map = {
            "width": cv2.CAP_PROP_FRAME_WIDTH,
            "height": cv2.CAP_PROP_FRAME_HEIGHT,
            "fps": cv2.CAP_PROP_FPS,
            "brightness": cv2.CAP_PROP_BRIGHTNESS,
            "contrast": cv2.CAP_PROP_CONTRAST,
            "saturation": cv2.CAP_PROP_SATURATION,
            "exposure": cv2.CAP_PROP_EXPOSURE,
            "auto_exposure": cv2.CAP_PROP_AUTO_EXPOSURE,
            "gain": cv2.CAP_PROP_GAIN,
            "focus": cv2.CAP_PROP_FOCUS,
            "autofocus": cv2.CAP_PROP_AUTOFOCUS,
        }

        for name, prop_id in prop_map.items():
            try:
                props[name] = self._cap.get(prop_id)
            except Exception:
                props[name] = None

        return props

    def set_property(self, name: str, value: float) -> bool:
        """Set camera property."""
        if not self.is_open():
            return False

        prop_map = {
            "width": cv2.CAP_PROP_FRAME_WIDTH,
            "height": cv2.CAP_PROP_FRAME_HEIGHT,
            "fps": cv2.CAP_PROP_FPS,
            "brightness": cv2.CAP_PROP_BRIGHTNESS,
            "contrast": cv2.CAP_PROP_CONTRAST,
            "saturation": cv2.CAP_PROP_SATURATION,
            "exposure": cv2.CAP_PROP_EXPOSURE,
            "auto_exposure": cv2.CAP_PROP_AUTO_EXPOSURE,
            "gain": cv2.CAP_PROP_GAIN,
            "focus": cv2.CAP_PROP_FOCUS,
            "autofocus": cv2.CAP_PROP_AUTOFOCUS,
        }

        prop_id = prop_map.get(name)
        if prop_id is None:
            return False

        try:
            return self._cap.set(prop_id, value)
        except Exception as e:
            logger.error(f"Error setting property {name}: {e}")
            return False


# Global instance
_camera_manager: Optional[CameraManager] = None


def get_camera_manager(config: CameraConfig = None) -> CameraManager:
    """Get or create global CameraManager instance."""
    global _camera_manager
    if _camera_manager is None:
        _camera_manager = CameraManager(config)
    return _camera_manager


# High-level async functions for tool integration
async def camera_open(device_index: int = 0, width: int = 1280, height: int = 720, fps: int = 30) -> dict:
    """Open camera with specified settings."""
    config = CameraConfig(device_index=device_index, width=width, height=height, fps=fps)
    manager = get_camera_manager(config)
    success = manager.open()
    return {"success": success, "config": {"device_index": device_index, "width": width, "height": height, "fps": fps}}


async def camera_close() -> dict:
    """Close camera."""
    global _camera_manager
    if _camera_manager:
        _camera_manager.close()
        _camera_manager = None
    return {"success": True}


async def camera_capture(save_path: str = None, format: str = "jpg") -> dict:
    """Capture a single frame."""
    manager = get_camera_manager()
    if not manager.is_open():
        if not manager.open():
            return {"success": False, "error": "Failed to open camera"}

    if save_path:
        success = manager.capture_to_file(save_path, format)
        return {"success": success, "path": save_path}

    frame = manager.capture_frame()
    if frame is None:
        return {"success": False, "error": "Failed to capture frame"}

    return {
        "success": True,
        "width": frame.width,
        "height": frame.height,
        "timestamp": frame.timestamp,
        "frame_number": frame.frame_number
    }


async def camera_list() -> dict:
    """List available cameras."""
    manager = get_camera_manager()
    cameras = manager.list_cameras()
    return {"success": True, "cameras": cameras}


async def camera_get_properties() -> dict:
    """Get current camera properties."""
    manager = get_camera_manager()
    if not manager.is_open():
        return {"success": False, "error": "Camera not open"}
    props = manager.get_properties()
    return {"success": True, "properties": props}


async def camera_set_property(name: str, value: float) -> dict:
    """Set camera property."""
    manager = get_camera_manager()
    if not manager.is_open():
        return {"success": False, "error": "Camera not open"}
    success = manager.set_property(name, value)
    return {"success": success, "property": name, "value": value}


async def camera_start_stream(callback: Callable = None) -> dict:
    """Start continuous capture."""
    manager = get_camera_manager()
    if not manager.is_open():
        if not manager.open():
            return {"success": False, "error": "Failed to open camera"}

    success = manager.start_capture(callback)
    return {"success": success}


async def camera_stop_stream() -> dict:
    """Stop continuous capture."""
    manager = get_camera_manager()
    manager.stop_capture()
    return {"success": True}