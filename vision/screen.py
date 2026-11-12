"""
Screen Module - Screen capture, OCR, and screen analysis for JARVIS.
Uses mss for fast cross-platform capture, pytesseract for OCR.
"""
from __future__ import annotations
import asyncio
import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, List, Dict, Any, Tuple
import threading

import cv2
import numpy as np
import mss
import mss.tools

# Optional OCR
try:
    import pytesseract
    TESSERACT_AVAILABLE = True
except ImportError:
    TESSERACT_AVAILABLE = False
    pytesseract = None

logger = logging.getLogger(__name__)


@dataclass
class MonitorInfo:
    """Monitor information."""
    index: int
    left: int
    top: int
    width: int
    height: int
    is_primary: bool = False


@dataclass
class ScreenRegion:
    """Screen region coordinates."""
    left: int
    top: int
    width: int
    height: int

    def to_mss(self) -> dict:
        return {"left": self.left, "top": self.top, "width": self.width, "height": self.height}

    def to_tuple(self) -> Tuple[int, int, int, int]:
        return (self.left, self.top, self.width, self.height)

    def contains(self, x: int, y: int) -> bool:
        return (self.left <= x < self.left + self.width and
                self.top <= y < self.top + self.height)


@dataclass
class ScreenCapture:
    """Captured screen image with metadata."""
    image: np.ndarray  # BGR format (OpenCV)
    monitor: MonitorInfo
    region: Optional[ScreenRegion]
    timestamp: float
    frame_number: int


class ScreenManager:
    """
    Manages screen capture using mss (fast, cross-platform).
    Supports full screen, monitor-specific, and region capture.
    """

    def __init__(self):
        self._sct: Optional[mss.mss] = None
        self._monitors: List[MonitorInfo] = []
        self._running = False
        self._capture_thread: Optional[threading.Thread] = None
        self._frame_queue: asyncio.Queue = asyncio.Queue(maxsize=10)
        self._frame_count = 0
        self._last_capture: Optional[ScreenCapture] = None
        self._lock = threading.Lock()
        self._initialize()

    def _initialize(self) -> None:
        """Initialize mss and detect monitors."""
        try:
            self._sct = mss.mss()
            # mss.monitors[0] is all monitors combined, [1:] are individual
            for i, mon in enumerate(self._sct.monitors[1:], 1):
                self._monitors.append(MonitorInfo(
                    index=i,
                    left=mon["left"],
                    top=mon["top"],
                    width=mon["width"],
                    height=mon["height"],
                    is_primary=(i == 1)
                ))
            logger.info(f"ScreenManager initialized with {len(self._monitors)} monitor(s)")
        except Exception as e:
            logger.error(f"Failed to initialize screen capture: {e}")
            self._sct = None

    def get_monitors(self) -> List[MonitorInfo]:
        """Get list of available monitors."""
        return self._monitors

    def get_primary_monitor(self) -> Optional[MonitorInfo]:
        """Get primary monitor."""
        for m in self._monitors:
            if m.is_primary:
                return m
        return self._monitors[0] if self._monitors else None

    def capture(self, monitor_index: int = 0, region: ScreenRegion = None) -> Optional[ScreenCapture]:
        """
        Capture screen synchronously.

        Args:
            monitor_index: Monitor index (0 = all monitors combined, 1+ = specific monitor)
            region: Specific region to capture (relative to monitor)
        """
        if not self._sct:
            return None

        try:
            if monitor_index == 0:
                # All monitors combined
                monitor = self._sct.monitors[0]
                mon_info = MonitorInfo(
                    index=0,
                    left=monitor["left"],
                    top=monitor["top"],
                    width=monitor["width"],
                    height=monitor["height"]
                )
            elif 1 <= monitor_index <= len(self._monitors):
                monitor = self._sct.monitors[monitor_index]
                mon_info = self._monitors[monitor_index - 1]
            else:
                logger.error(f"Invalid monitor index: {monitor_index}")
                return None

            # Determine capture region
            if region:
                capture_region = {
                    "left": monitor["left"] + region.left,
                    "top": monitor["top"] + region.top,
                    "width": region.width,
                    "height": region.height
                }
            else:
                capture_region = monitor

            # Capture
            screenshot = self._sct.grab(capture_region)

            # Convert to numpy array (BGRA -> BGR)
            img = np.array(screenshot)
            img = cv2.cvtColor(img, cv2.COLOR_BGRA2BGR)

            self._frame_count += 1
            capture = ScreenCapture(
                image=img,
                monitor=mon_info,
                region=region,
                timestamp=time.time(),
                frame_number=self._frame_count
            )
            self._last_capture = capture
            return capture

        except Exception as e:
            logger.error(f"Screen capture error: {e}")
            return None

    def capture_to_file(self, path: str, monitor_index: int = 0, region: ScreenRegion = None, format: str = "png") -> bool:
        """Capture screen and save to file."""
        capture = self.capture(monitor_index, region)
        if capture is None:
            return False

        try:
            path = Path(path)
            if format.lower() == "png":
                path = path.with_suffix(".png")
                cv2.imwrite(str(path), capture.image, [cv2.IMWRITE_PNG_COMPRESSION, 3])
            elif format.lower() in ("jpg", "jpeg"):
                path = path.with_suffix(".jpg")
                cv2.imwrite(str(path), capture.image, [cv2.IMWRITE_JPEG_QUALITY, 90])
            else:
                path = path.with_suffix(f".{format}")
                cv2.imwrite(str(path), capture.image)

            logger.info(f"Screen capture saved to {path}")
            return True
        except Exception as e:
            logger.error(f"Error saving screen capture: {e}")
            return False

    def capture_window(self, window_title: str) -> Optional[ScreenCapture]:
        """Capture specific window by title (Windows only)."""
        try:
            import pygetwindow as gw
            windows = gw.getWindowsWithTitle(window_title)
            if not windows:
                logger.warning(f"Window not found: {window_title}")
                return None

            win = windows[0]
            region = ScreenRegion(
                left=win.left,
                top=win.top,
                width=win.width,
                height=win.height
            )
            return self.capture(monitor_index=0, region=region)
        except Exception as e:
            logger.error(f"Window capture error: {e}")
            return None

    def start_continuous_capture(self, monitor_index: int = 0, region: ScreenRegion = None, fps: float = 10) -> bool:
        """Start continuous capture in background thread."""
        if self._running:
            logger.warning("Continuous capture already running")
            return True

        if not self._sct:
            return False

        self._running = True
        interval = 1.0 / fps

        def capture_loop():
            while self._running:
                start = time.time()
                capture = self.capture(monitor_index, region)
                if capture:
                    try:
                        self._frame_queue.put_nowait(capture)
                    except asyncio.QueueFull:
                        try:
                            self._frame_queue.get_nowait()
                            self._frame_queue.put_nowait(capture)
                        except Exception:
                            pass

                elapsed = time.time() - start
                sleep_time = max(0, interval - elapsed)
                if sleep_time > 0:
                    time.sleep(sleep_time)

        self._capture_thread = threading.Thread(target=capture_loop, daemon=True)
        self._capture_thread.start()
        logger.info(f"Continuous screen capture started at {fps}fps")
        return True

    def stop_continuous_capture(self) -> None:
        """Stop continuous capture."""
        self._running = False
        if self._capture_thread and self._capture_thread.is_alive():
            self._capture_thread.join(timeout=2.0)
            self._capture_thread = None
        logger.info("Continuous screen capture stopped")

    async def get_capture_async(self, monitor_index: int = 0, region: ScreenRegion = None, timeout: float = 1.0) -> Optional[ScreenCapture]:
        """Get capture asynchronously (runs in executor)."""
        loop = asyncio.get_event_loop()
        return await asyncio.wait_for(
            loop.run_in_executor(None, self.capture, monitor_index, region),
            timeout=timeout
        )

    async def stream_captures(self, monitor_index: int = 0, region: ScreenRegion = None, max_fps: float = 10) -> Any:
        """Async generator for streaming screen captures."""
        if not self._running:
            self.start_continuous_capture(monitor_index, region, max_fps)

        min_interval = 1.0 / max_fps
        last_yield = 0

        while self._running:
            try:
                capture = await asyncio.wait_for(self._frame_queue.get(), timeout=2.0)
            except asyncio.TimeoutError:
                continue

            now = time.time()
            if now - last_yield >= min_interval:
                yield capture
                last_yield = now
            else:
                try:
                    self._frame_queue.put_nowait(capture)
                except Exception:
                    pass
                await asyncio.sleep(min_interval - (now - last_yield))

    def get_last_capture(self) -> Optional[ScreenCapture]:
        """Get last captured frame."""
        return self._last_capture


class OCRManager:
    """
    OCR (Optical Character Recognition) using Tesseract.
    Extracts text from screen captures or images.
    """

    def __init__(self, tesseract_path: str = None):
        self.tesseract_path = tesseract_path
        if tesseract_path and TESSERACT_AVAILABLE:
            pytesseract.pytesseract.tesseract_cmd = tesseract_path

    def is_available(self) -> bool:
        """Check if Tesseract is available."""
        return TESSERACT_AVAILABLE

    def extract_text(self, image: np.ndarray, lang: str = "por+eng", config: str = "") -> str:
        """Extract text from image."""
        if not TESSERACT_AVAILABLE:
            return ""

        try:
            # Preprocess for better OCR
            gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
            # Increase contrast
            gray = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)[1]

            text = pytesseract.image_to_string(gray, lang=lang, config=config)
            return text.strip()
        except Exception as e:
            logger.error(f"OCR error: {e}")
            return ""

    def extract_text_detailed(self, image: np.ndarray, lang: str = "por+eng") -> List[Dict]:
        """Extract text with position and confidence data."""
        if not TESSERACT_AVAILABLE:
            return []

        try:
            gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
            gray = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)[1]

            data = pytesseract.image_to_data(gray, lang=lang, output_type=pytesseract.Output.DICT)

            results = []
            for i in range(len(data["text"])):
                text = data["text"][i].strip()
                if text:
                    results.append({
                        "text": text,
                        "left": data["left"][i],
                        "top": data["top"][i],
                        "width": data["width"][i],
                        "height": data["height"][i],
                        "confidence": data["conf"][i],
                        "block_num": data["block_num"][i],
                        "line_num": data["line_num"][i],
                        "word_num": data["word_num"][i]
                    })
            return results
        except Exception as e:
            logger.error(f"OCR detailed error: {e}")
            return []

    def find_text(self, image: np.ndarray, search_text: str, lang: str = "por+eng") -> List[Dict]:
        """Find specific text in image and return positions."""
        results = self.extract_text_detailed(image, lang)
        matches = []
        search_lower = search_text.lower()

        for r in results:
            if search_lower in r["text"].lower():
                matches.append(r)

        return matches


class TemplateMatcher:
    """
    Template matching for finding images/icons on screen.
    """

    def __init__(self):
        self._cache: Dict[str, np.ndarray] = {}

    def load_template(self, path: str, name: str = None) -> bool:
        """Load template image for matching."""
        try:
            template = cv2.imread(path, cv2.IMREAD_COLOR)
            if template is None:
                logger.error(f"Failed to load template: {path}")
                return False

            key = name or Path(path).stem
            self._cache[key] = template
            return True
        except Exception as e:
            logger.error(f"Error loading template: {e}")
            return False

    def find_template(
        self,
        screen: np.ndarray,
        template_name: str,
        threshold: float = 0.8,
        method: int = cv2.TM_CCOEFF_NORMED
    ) -> List[Dict]:
        """Find template on screen."""
        template = self._cache.get(template_name)
        if template is None:
            return []

        try:
            result = cv2.matchTemplate(screen, template, method)
            locations = np.where(result >= threshold)

            matches = []
            h, w = template.shape[:2]

            for pt in zip(*locations[::-1]):
                matches.append({
                    "x": int(pt[0]),
                    "y": int(pt[1]),
                    "width": w,
                    "height": h,
                    "confidence": float(result[pt[1], pt[0]]),
                    "center_x": int(pt[0] + w / 2),
                    "center_y": int(pt[1] + h / 2)
                })

            # Sort by confidence
            matches.sort(key=lambda m: m["confidence"], reverse=True)
            return matches

        except Exception as e:
            logger.error(f"Template matching error: {e}")
            return []

    def find_best_match(
        self,
        screen: np.ndarray,
        template_name: str,
        threshold: float = 0.8
    ) -> Optional[Dict]:
        """Find best single match."""
        matches = self.find_template(screen, template_name, threshold)
        return matches[0] if matches else None


# Global instances
_screen_manager: Optional[ScreenManager] = None
_ocr_manager: Optional[OCRManager] = None
_template_matcher: Optional[TemplateMatcher] = None


def get_screen_manager() -> ScreenManager:
    """Get or create global ScreenManager instance."""
    global _screen_manager
    if _screen_manager is None:
        _screen_manager = ScreenManager()
    return _screen_manager


def get_ocr_manager(tesseract_path: str = None) -> OCRManager:
    """Get or create global OCRManager instance."""
    global _ocr_manager
    if _ocr_manager is None:
        _ocr_manager = OCRManager(tesseract_path)
    return _ocr_manager


def get_template_matcher() -> TemplateMatcher:
    """Get or create global TemplateMatcher instance."""
    global _template_matcher
    if _template_matcher is None:
        _template_matcher = TemplateMatcher()
    return _template_matcher


# High-level async functions for tool integration
async def screen_capture(monitor: int = 0, region: dict = None, save_path: str = None) -> dict:
    """Capture screen."""
    manager = get_screen_manager()
    reg = ScreenRegion(**region) if region else None

    if save_path:
        success = manager.capture_to_file(save_path, monitor, reg)
        return {"success": success, "path": save_path}

    capture = await manager.get_capture_async(monitor, reg)
    if capture is None:
        return {"success": False, "error": "Capture failed"}

    return {
        "success": True,
        "width": capture.image.shape[1],
        "height": capture.image.shape[0],
        "monitor": capture.monitor.index,
        "timestamp": capture.timestamp
    }


async def screen_capture_window(window_title: str, save_path: str = None) -> dict:
    """Capture specific window."""
    manager = get_screen_manager()
    capture = await asyncio.get_event_loop().run_in_executor(
        None, manager.capture_window, window_title
    )

    if capture is None:
        return {"success": False, "error": "Window not found"}

    if save_path:
        cv2.imwrite(save_path, capture.image)
        return {"success": True, "path": save_path}

    return {
        "success": True,
        "width": capture.image.shape[1],
        "height": capture.image.shape[0],
        "timestamp": capture.timestamp
    }


async def screen_list_monitors() -> dict:
    """List available monitors."""
    manager = get_screen_manager()
    monitors = manager.get_monitors()
    return {
        "success": True,
        "monitors": [
            {
                "index": m.index,
                "left": m.left,
                "top": m.top,
                "width": m.width,
                "height": m.height,
                "is_primary": m.is_primary
            }
            for m in monitors
        ]
    }


async def screen_ocr(image_path: str = None, lang: str = "por+eng", region: dict = None) -> dict:
    """Extract text from image or screen region."""
    ocr = get_ocr_manager()

    if not ocr.is_available():
        return {"success": False, "error": "Tesseract not available. Install tesseract-ocr."}

    manager = get_screen_manager()

    if image_path:
        image = cv2.imread(image_path)
        if image is None:
            return {"success": False, "error": "Failed to load image"}
    else:
        reg = ScreenRegion(**region) if region else None
        capture = await manager.get_capture_async(0, reg)
        if capture is None:
            return {"success": False, "error": "Screen capture failed"}
        image = capture.image

    text = ocr.extract_text(image, lang=lang)
    return {"success": True, "text": text}


async def screen_ocr_detailed(image_path: str = None, lang: str = "por+eng", region: dict = None) -> dict:
    """Extract text with positions and confidence."""
    ocr = get_ocr_manager()

    if not ocr.is_available():
        return {"success": False, "error": "Tesseract not available"}

    manager = get_screen_manager()

    if image_path:
        image = cv2.imread(image_path)
        if image is None:
            return {"success": False, "error": "Failed to load image"}
    else:
        reg = ScreenRegion(**region) if region else None
        capture = await manager.get_capture_async(0, reg)
        if capture is None:
            return {"success": False, "error": "Screen capture failed"}
        image = capture.image

    results = ocr.extract_text_detailed(image, lang=lang)
    return {"success": True, "results": results}


async def screen_find_text(search_text: str, lang: str = "por+eng", region: dict = None) -> dict:
    """Find specific text on screen."""
    ocr = get_ocr_manager()

    if not ocr.is_available():
        return {"success": False, "error": "Tesseract not available"}

    manager = get_screen_manager()
    reg = ScreenRegion(**region) if region else None
    capture = await manager.get_capture_async(0, reg)

    if capture is None:
        return {"success": False, "error": "Screen capture failed"}

    matches = ocr.find_text(capture.image, search_text, lang)
    return {
        "success": True,
        "found": len(matches) > 0,
        "matches": matches
    }


async def screen_load_template(template_path: str, name: str = None) -> dict:
    """Load template for matching."""
    matcher = get_template_matcher()
    success = matcher.load_template(template_path, name)
    return {"success": success, "name": name or Path(template_path).stem}


async def screen_find_template(template_name: str, threshold: float = 0.8, region: dict = None) -> dict:
    """Find template on screen."""
    matcher = get_template_matcher()
    manager = get_screen_manager()

    reg = ScreenRegion(**region) if region else None
    capture = await manager.get_capture_async(0, reg)

    if capture is None:
        return {"success": False, "error": "Screen capture failed"}

    matches = matcher.find_template(capture.image, template_name, threshold)
    return {
        "success": True,
        "found": len(matches) > 0,
        "matches": matches
    }


async def screen_start_stream(monitor: int = 0, region: dict = None, fps: float = 10) -> dict:
    """Start continuous screen capture."""
    manager = get_screen_manager()
    reg = ScreenRegion(**region) if region else None
    success = manager.start_continuous_capture(monitor, reg, fps)
    return {"success": success}


async def screen_stop_stream() -> dict:
    """Stop continuous screen capture."""
    manager = get_screen_manager()
    manager.stop_continuous_capture()
    return {"success": True}