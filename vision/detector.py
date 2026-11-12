"""
Detector Module - Object detection using YOLO (Ultralytics) for JARVIS.
Supports person, object, face detection and custom models.
"""
from __future__ import annotations
import asyncio
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, List, Dict, Any, Union
import threading

import cv2
import numpy as np

# Optional YOLO
try:
    from ultralytics import YOLO
    YOLO_AVAILABLE = True
except ImportError:
    YOLO_AVAILABLE = False
    YOLO = None

logger = logging.getLogger(__name__)


@dataclass
class Detection:
    """Single detection result."""
    class_id: int
    class_name: str
    confidence: float
    bbox: tuple  # (x1, y1, x2, y2) in pixels
    center: tuple  # (cx, cy)
    width: int
    height: int


@dataclass
class DetectionResult:
    """Complete detection result for a frame."""
    detections: List[Detection]
    frame_width: int
    frame_height: int
    timestamp: float
    inference_time: float
    model_name: str


@dataclass
class DetectorConfig:
    """Detector configuration."""
    model_path: str = "yolov8n.pt"  # Nano model for speed
    confidence_threshold: float = 0.5
    iou_threshold: float = 0.45
    device: str = "auto"  # auto, cpu, cuda, mps
    classes: Optional[List[int]] = None  # Filter specific classes
    max_det: int = 100
    verbose: bool = False


class ObjectDetector:
    """
    YOLO-based object detector.
    Supports COCO classes by default, custom models supported.
    """

    # COCO class names
    COCO_CLASSES = {
        0: "person", 1: "bicycle", 2: "car", 3: "motorcycle", 4: "airplane",
        5: "bus", 6: "train", 7: "truck", 8: "boat", 9: "traffic light",
        10: "fire hydrant", 11: "stop sign", 12: "parking meter", 13: "bench",
        14: "bird", 15: "cat", 16: "dog", 17: "horse", 18: "sheep", 19: "cow",
        20: "elephant", 21: "bear", 22: "zebra", 23: "giraffe", 24: "backpack",
        25: "umbrella", 26: "handbag", 27: "tie", 28: "suitcase", 29: "frisbee",
        30: "skis", 31: "snowboard", 32: "sports ball", 33: "kite", 34: "baseball bat",
        35: "baseball glove", 36: "skateboard", 37: "surfboard", 38: "tennis racket",
        39: "bottle", 40: "wine glass", 41: "cup", 42: "fork", 43: "knife",
        44: "spoon", 45: "bowl", 46: "banana", 47: "apple", 48: "sandwich",
        49: "orange", 50: "broccoli", 51: "carrot", 52: "hot dog", 53: "pizza",
        54: "donut", 55: "cake", 56: "chair", 57: "couch", 58: "potted plant",
        59: "bed", 60: "dining table", 61: "toilet", 62: "tv", 63: "laptop",
        64: "mouse", 65: "remote", 66: "keyboard", 67: "cell phone", 68: "microwave",
        69: "oven", 70: "toaster", 71: "sink", 72: "refrigerator", 73: "book",
        74: "clock", 75: "vase", 76: "scissors", 77: "teddy bear", 78: "hair dryer",
        79: "toothbrush"
    }

    def __init__(self, config: DetectorConfig = None):
        self.config = config or DetectorConfig()
        self._model: Optional[YOLO] = None
        self._loaded = False
        self._class_names = self.COCO_CLASSES.copy()

    def load(self) -> bool:
        """Load YOLO model."""
        if not YOLO_AVAILABLE:
            logger.error("Ultralytics not installed. Run: pip install ultralytics")
            return False

        if self._loaded:
            return True

        try:
            self._model = YOLO(self.config.model_path)
            self._model.to(self.config.device)
            self._loaded = True

            # Update class names if custom model
            if hasattr(self._model, 'names'):
                self._class_names = self._model.names

            logger.info(f"YOLO model loaded: {self.config.model_path} on {self.config.device}")
            return True
        except Exception as e:
            logger.error(f"Failed to load YOLO model: {e}")
            return False

    def unload(self) -> None:
        """Unload model to free memory."""
        self._model = None
        self._loaded = False
        logger.info("YOLO model unloaded")

    def is_loaded(self) -> bool:
        return self._loaded

    def get_class_names(self) -> Dict[int, str]:
        """Get class ID to name mapping."""
        return self._class_names.copy()

    def detect(self, image: np.ndarray) -> DetectionResult:
        """
        Run detection on image.

        Args:
            image: BGR image (OpenCV format)

        Returns:
            DetectionResult with all detections
        """
        if not self._loaded:
            if not self.load():
                return DetectionResult(
                    detections=[],
                    frame_width=image.shape[1],
                    frame_height=image.shape[0],
                    timestamp=time.time(),
                    inference_time=0,
                    model_name=self.config.model_path
                )

        start_time = time.time()

        try:
            results = self._model.predict(
                source=image,
                conf=self.config.confidence_threshold,
                iou=self.config.iou_threshold,
                classes=self.config.classes,
                max_det=self.config.max_det,
                verbose=self.config.verbose,
                device=self.config.device
            )

            inference_time = time.time() - start_time

            detections = []
            if results and len(results) > 0:
                result = results[0]
                if result.boxes is not None:
                    boxes = result.boxes.xyxy.cpu().numpy()  # x1, y1, x2, y2
                    confidences = result.boxes.conf.cpu().numpy()
                    class_ids = result.boxes.cls.cpu().numpy().astype(int)

                    for box, conf, cls_id in zip(boxes, confidences, class_ids):
                        x1, y1, x2, y2 = map(int, box)
                        cx = (x1 + x2) // 2
                        cy = (y1 + y2) // 2
                        w = x2 - x1
                        h = y2 - y1

                        class_name = self._class_names.get(cls_id, f"class_{cls_id}")

                        detections.append(Detection(
                            class_id=cls_id,
                            class_name=class_name,
                            confidence=float(conf),
                            bbox=(x1, y1, x2, y2),
                            center=(cx, cy),
                            width=w,
                            height=h
                        ))

            return DetectionResult(
                detections=detections,
                frame_width=image.shape[1],
                frame_height=image.shape[0],
                timestamp=time.time(),
                inference_time=inference_time,
                model_name=self.config.model_path
            )

        except Exception as e:
            logger.error(f"Detection error: {e}")
            return DetectionResult(
                detections=[],
                frame_width=image.shape[1],
                frame_height=image.shape[0],
                timestamp=time.time(),
                inference_time=time.time() - start_time,
                model_name=self.config.model_path
            )

    def detect_async(self, image: np.ndarray) -> asyncio.Future:
        """Run detection in executor (async)."""
        loop = asyncio.get_event_loop()
        return loop.run_in_executor(None, self.detect, image)

    def draw_detections(
        self,
        image: np.ndarray,
        result: DetectionResult,
        draw_labels: bool = True,
        draw_confidence: bool = True,
        color_map: Dict[str, tuple] = None
    ) -> np.ndarray:
        """Draw detection boxes on image."""
        annotated = image.copy()

        for det in result.detections:
            x1, y1, x2, y2 = det.bbox

            # Get color for class
            if color_map and det.class_name in color_map:
                color = color_map[det.class_name]
            else:
                # Generate consistent color from class_id
                np.random.seed(det.class_id)
                color = tuple(map(int, np.random.randint(0, 255, 3)))
                np.random.seed()

            # Draw box
            cv2.rectangle(annotated, (x1, y1), (x2, y2), color, 2)

            # Draw label
            if draw_labels:
                label = det.class_name
                if draw_confidence:
                    label += f" {det.confidence:.2f}"

                (text_w, text_h), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1)
                cv2.rectangle(annotated, (x1, y1 - text_h - 4), (x1 + text_w, y1), color, -1)
                cv2.putText(annotated, label, (x1, y1 - 2), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)

        return annotated

    def filter_detections(
        self,
        result: DetectionResult,
        classes: List[str] = None,
        min_confidence: float = None,
        min_area: int = None,
        max_area: int = None
    ) -> DetectionResult:
        """Filter detections by criteria."""
        filtered = []

        for det in result.detections:
            if classes and det.class_name not in classes:
                continue
            if min_confidence and det.confidence < min_confidence:
                continue
            if min_area and (det.width * det.height) < min_area:
                continue
            if max_area and (det.width * det.height) > max_area:
                continue
            filtered.append(det)

        return DetectionResult(
            detections=filtered,
            frame_width=result.frame_width,
            frame_height=result.frame_height,
            timestamp=result.timestamp,
            inference_time=result.inference_time,
            model_name=result.model_name
        )

    def count_objects(self, result: DetectionResult) -> Dict[str, int]:
        """Count objects by class."""
        counts = {}
        for det in result.detections:
            counts[det.class_name] = counts.get(det.class_name, 0) + 1
        return counts


class FaceDetector:
    """
    Face detection using OpenCV DNN (no extra dependencies).
    Can also use YOLO face models if available.
    """

    def __init__(self, use_yolo: bool = False, yolo_model: str = "yolov8n-face.pt"):
        self.use_yolo = use_yolo and YOLO_AVAILABLE
        self.yolo_model = yolo_model
        self._yolo_detector: Optional[ObjectDetector] = None
        self._opencv_net = None
        self._initialize_opencv()

    def _initialize_opencv(self) -> None:
        """Initialize OpenCV DNN face detector."""
        try:
            # Use OpenCV's built-in face detector (DNN)
            model_path = cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
            self._opencv_cascade = cv2.CascadeClassifier(model_path)
        except Exception as e:
            logger.warning(f"OpenCV face cascade not available: {e}")
            self._opencv_cascade = None

    def load_yolo(self) -> bool:
        """Load YOLO face model."""
        if not self.use_yolo:
            return False

        config = DetectorConfig(model_path=self.yolo_model, confidence_threshold=0.5)
        self._yolo_detector = ObjectDetector(config)
        return self._yolo_detector.load()

    def detect(self, image: np.ndarray) -> List[Detection]:
        """Detect faces in image."""
        if self.use_yolo and self._yolo_detector:
            result = self._yolo_detector.detect(image)
            return [d for d in result.detections if d.class_name.lower() in ("face", "person")]
        elif self._opencv_cascade:
            return self._detect_opencv(image)
        return []

    def _detect_opencv(self, image: np.ndarray) -> List[Detection]:
        """Detect using OpenCV Haar cascade."""
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        faces = self._opencv_cascade.detectMultiScale(
            gray, scaleFactor=1.1, minNeighbors=5, minSize=(30, 30)
        )

        detections = []
        for (x, y, w, h) in faces:
            detections.append(Detection(
                class_id=0,
                class_name="face",
                confidence=0.9,  # Haar doesn't give confidence
                bbox=(x, y, x + w, y + h),
                center=(x + w // 2, y + h // 2),
                width=w,
                height=h
            ))
        return detections


class MotionDetector:
    """
    Simple motion detection using frame differencing.
    Useful for detecting movement in camera feeds.
    """

    def __init__(self, threshold: int = 25, min_area: int = 500):
        self.threshold = threshold
        self.min_area = min_area
        self._background: Optional[np.ndarray] = None
        self._learning_rate = 0.01

    def update_background(self, frame: np.ndarray) -> None:
        """Update background model."""
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        gray = cv2.GaussianBlur(gray, (21, 21), 0)

        if self._background is None:
            self._background = gray.astype("float")
        else:
            cv2.accumulateWeighted(gray, self._background, self._learning_rate)

    def detect(self, frame: np.ndarray) -> List[Detection]:
        """Detect motion in frame."""
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        gray = cv2.GaussianBlur(gray, (21, 21), 0)

        if self._background is None:
            self._background = gray.astype("float")
            return []

        # Compute difference
        background_uint8 = self._background.astype("uint8")
        frame_delta = cv2.absdiff(background_uint8, gray)
        thresh = cv2.threshold(frame_delta, self.threshold, 255, cv2.THRESH_BINARY)[1]
        thresh = cv2.dilate(thresh, None, iterations=2)

        # Find contours
        contours, _ = cv2.findContours(thresh.copy(), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

        detections = []
        for contour in contours:
            area = cv2.contourArea(contour)
            if area < self.min_area:
                continue

            x, y, w, h = cv2.boundingRect(contour)
            detections.append(Detection(
                class_id=0,
                class_name="motion",
                confidence=min(1.0, area / 10000),
                bbox=(x, y, x + w, y + h),
                center=(x + w // 2, y + h // 2),
                width=w,
                height=h
            ))

        return detections

    def reset(self) -> None:
        """Reset background model."""
        self._background = None


# Global instances
_object_detector: Optional[ObjectDetector] = None
_face_detector: Optional[FaceDetector] = None
_motion_detector: Optional[MotionDetector] = None


def get_object_detector(config: DetectorConfig = None) -> ObjectDetector:
    """Get or create global ObjectDetector instance."""
    global _object_detector
    if _object_detector is None:
        _object_detector = ObjectDetector(config)
    return _object_detector


def get_face_detector(use_yolo: bool = False, yolo_model: str = "yolov8n-face.pt") -> FaceDetector:
    """Get or create global FaceDetector instance."""
    global _face_detector
    if _face_detector is None:
        _face_detector = FaceDetector(use_yolo, yolo_model)
    return _face_detector


def get_motion_detector(threshold: int = 25, min_area: int = 500) -> MotionDetector:
    """Get or create global MotionDetector instance."""
    global _motion_detector
    if _motion_detector is None:
        _motion_detector = MotionDetector(threshold, min_area)
    return _motion_detector


# High-level async functions for tool integration
async def detector_load_model(model_path: str = "yolov8n.pt", device: str = "auto", conf: float = 0.5) -> dict:
    """Load YOLO detection model."""
    config = DetectorConfig(model_path=model_path, device=device, confidence_threshold=conf)
    detector = get_object_detector(config)
    success = detector.load()
    return {"success": success, "model": model_path, "device": device}


async def detector_unload_model() -> dict:
    """Unload detection model."""
    global _object_detector
    if _object_detector:
        _object_detector.unload()
        _object_detector = None
    return {"success": True}


async def detector_detect(image_path: str = None, classes: list = None, min_conf: float = None) -> dict:
    """Run object detection on image or screen."""
    detector = get_object_detector()

    if not detector.is_loaded():
        if not detector.load():
            return {"success": False, "error": "Failed to load model"}

    # Get image
    if image_path:
        image = cv2.imread(image_path)
        if image is None:
            return {"success": False, "error": "Failed to load image"}
    else:
        # Capture from screen
        from vision.screen import get_screen_manager
        manager = get_screen_manager()
        capture = await manager.get_capture_async()
        if capture is None:
            return {"success": False, "error": "Screen capture failed"}
        image = capture.image

    # Run detection
    result = await detector.detect_async(image)

    # Filter if needed
    if classes or min_conf:
        result = detector.filter_detections(
            result,
            classes=classes,
            min_confidence=min_conf
        )

    return {
        "success": True,
        "detections": [
            {
                "class_id": d.class_id,
                "class_name": d.class_name,
                "confidence": d.confidence,
                "bbox": {"x1": d.bbox[0], "y1": d.bbox[1], "x2": d.bbox[2], "y2": d.bbox[3]},
                "center": {"x": d.center[0], "y": d.center[1]},
                "width": d.width,
                "height": d.height
            }
            for d in result.detections
        ],
        "counts": detector.count_objects(result),
        "inference_time": result.inference_time,
        "frame_size": {"width": result.frame_width, "height": result.frame_height}
    }


async def detector_detect_and_annotate(image_path: str, output_path: str = None, **kwargs) -> dict:
    """Detect objects and save annotated image."""
    detector = get_object_detector()

    if not detector.is_loaded():
        if not detector.load():
            return {"success": False, "error": "Failed to load model"}

    image = cv2.imread(image_path)
    if image is None:
        return {"success": False, "error": "Failed to load image"}

    result = await detector.detect_async(image)
    annotated = detector.draw_detections(image, result)

    if output_path:
        cv2.imwrite(output_path, annotated)
        return {"success": True, "output_path": output_path, "detections": len(result.detections)}

    return {"success": True, "detections": len(result.detections), "annotated": "returned_as_array"}


async def detector_get_classes() -> dict:
    """Get available detection classes."""
    detector = get_object_detector()
    return {"success": True, "classes": detector.get_class_names()}


async def face_detect(image_path: str = None, use_yolo: bool = False) -> dict:
    """Detect faces in image."""
    face_detector = get_face_detector(use_yolo=use_yolo)

    if use_yolo:
        face_detector.load_yolo()

    if image_path:
        image = cv2.imread(image_path)
        if image is None:
            return {"success": False, "error": "Failed to load image"}
    else:
        from vision.screen import get_screen_manager
        manager = get_screen_manager()
        capture = await manager.get_capture_async()
        if capture is None:
            return {"success": False, "error": "Screen capture failed"}
        image = capture.image

    detections = face_detector.detect(image)

    return {
        "success": True,
        "faces": [
            {
                "bbox": {"x1": d.bbox[0], "y1": d.bbox[1], "x2": d.bbox[2], "y2": d.bbox[3]},
                "center": {"x": d.center[0], "y": d.center[1]},
                "confidence": d.confidence
            }
            for d in detections
        ],
        "count": len(detections)
    }


async def motion_detect(threshold: int = 25, min_area: int = 500, image_path: str = None) -> dict:
    """Detect motion in frame."""
    motion_detector = get_motion_detector(threshold, min_area)

    if image_path:
        frame = cv2.imread(image_path)
        if frame is None:
            return {"success": False, "error": "Failed to load image"}
    else:
        from vision.screen import get_screen_manager
        manager = get_screen_manager()
        capture = await manager.get_capture_async()
        if capture is None:
            return {"success": False, "error": "Screen capture failed"}
        frame = capture.image

    detections = motion_detector.detect(frame)

    return {
        "success": True,
        "motion_detected": len(detections) > 0,
        "detections": [
            {
                "bbox": {"x1": d.bbox[0], "y1": d.bbox[1], "x2": d.bbox[2], "y2": d.bbox[3]},
                "center": {"x": d.center[0], "y": d.center[1]},
                "area": d.width * d.height
            }
            for d in detections
        ]
    }


async def motion_reset() -> dict:
    """Reset motion detector background."""
    motion_detector = get_motion_detector()
    motion_detector.reset()
    return {"success": True}