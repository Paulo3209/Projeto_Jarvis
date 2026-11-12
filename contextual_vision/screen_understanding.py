"""
Screen Understanding - Real-time screen analysis and UI comprehension.
Uses OCR, object detection, and layout analysis to understand screen content.
"""
from __future__ import annotations
import asyncio
import base64
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple
from pathlib import Path

import cv2
import numpy as np

from vision.screen import get_screen_manager, get_ocr_manager, ScreenCapture
from vision.detector import get_object_detector, Detection

logger = logging.getLogger(__name__)


class UIElementType(Enum):
    """Types of UI elements."""
    BUTTON = "button"
    TEXT_FIELD = "text_field"
    LINK = "link"
    IMAGE = "image"
    ICON = "icon"
    MENU = "menu"
    TAB = "tab"
    WINDOW = "window"
    DIALOG = "dialog"
    SCROLLBAR = "scrollbar"
    CHECKBOX = "checkbox"
    RADIO = "radio"
    DROPDOWN = "dropdown"
    SLIDER = "slider"
    PROGRESS = "progress"
    TEXT = "text"
    UNKNOWN = "unknown"


@dataclass
class UIElement:
    """Detected UI element."""
    element_id: str
    element_type: UIElementType
    bounds: Tuple[int, int, int, int]  # x, y, width, height
    text: str = ""
    confidence: float = 0.0
    attributes: Dict = field(default_factory=dict)
    children: List['UIElement'] = field(default_factory=list)
    parent: Optional['UIElement'] = None

    @property
    def center(self) -> Tuple[int, int]:
        x, y, w, h = self.bounds
        return (x + w // 2, y + h // 2)

    @property
    def area(self) -> int:
        _, _, w, h = self.bounds
        return w * h

    def contains_point(self, x: int, y: int) -> bool:
        ex, ey, ew, eh = self.bounds
        return ex <= x <= ex + ew and ey <= y <= ey + eh

    def to_dict(self) -> Dict:
        return {
            "element_id": self.element_id,
            "type": self.element_type.value,
            "bounds": self.bounds,
            "text": self.text,
            "confidence": self.confidence,
            "attributes": self.attributes,
            "center": self.center,
        }


@dataclass
class ScreenContext:
    """Complete screen understanding context."""
    timestamp: datetime
    monitor: int
    resolution: Tuple[int, int]
    elements: List[UIElement]
    text_content: str
    active_window: Optional[str] = None
    application: Optional[str] = None
    layout_structure: Dict = field(default_factory=dict)
    changes_from_previous: List[Dict] = field(default_factory=list)

    def get_elements_by_type(self, element_type: UIElementType) -> List[UIElement]:
        return [e for e in self.elements if e.element_type == element_type]

    def get_elements_containing_text(self, text: str) -> List[UIElement]:
        return [e for e in self.elements if text.lower() in e.text.lower()]

    def get_clickable_elements(self) -> List[UIElement]:
        clickable_types = {
            UIElementType.BUTTON, UIElementType.LINK, UIElementType.MENU,
            UIElementType.TAB, UIElementType.CHECKBOX, UIElementType.RADIO,
            UIElementType.DROPDOWN, UIElementType.SLIDER,
        }
        return [e for e in self.elements if e.element_type in clickable_types]

    def to_dict(self) -> Dict:
        return {
            "timestamp": self.timestamp.isoformat(),
            "monitor": self.monitor,
            "resolution": self.resolution,
            "active_window": self.active_window,
            "application": self.application,
            "text_content": self.text_content[:500],
            "elements": [e.to_dict() for e in self.elements],
            "layout_structure": self.layout_structure,
        }


class ScreenUnderstanding:
    """
    Real-time screen understanding using OCR, object detection, and layout analysis.
    """

    def __init__(self):
        self._screen_manager = get_screen_manager()
        self._ocr_manager = get_ocr_manager()
        self._object_detector = get_object_detector()
        self._previous_context: Optional[ScreenContext] = None
        self._running = False
        self._callbacks: List[callable] = []

    def add_callback(self, callback: callable) -> None:
        """Add callback for screen context updates."""
        self._callbacks.append(callback)

    async def analyze_screen(self, monitor: int = 0, use_cache: bool = True) -> ScreenContext:
        """Analyze current screen and return context."""
        start_time = time.time()

        # Capture screen
        capture = await self._screen_manager.capture(monitor=monitor)

        # Run OCR and object detection in parallel
        ocr_task = asyncio.create_task(self._run_ocr(capture))
        detect_task = asyncio.create_task(self._run_detection(capture))

        ocr_result, detections = await asyncio.gather(ocr_task, detect_task)

        # Build UI elements from OCR and detections
        elements = self._build_ui_elements(ocr_result, detections, capture)

        # Detect active window/application
        active_window, application = await self._detect_active_window(elements)

        # Build layout structure
        layout = self._build_layout_structure(elements)

        # Detect changes from previous
        changes = []
        if self._previous_context:
            changes = self._detect_changes(self._previous_context, elements)

        context = ScreenContext(
            timestamp=datetime.now(),
            monitor=monitor,
            resolution=(capture.width, capture.height),
            elements=elements,
            text_content=ocr_result.get("text", ""),
            active_window=active_window,
            application=application,
            layout_structure=layout,
            changes_from_previous=changes,
        )

        self._previous_context = context

        # Notify callbacks
        for callback in self._callbacks:
            try:
                await callback(context)
            except Exception as e:
                logger.error(f"Callback error: {e}")

        logger.debug(f"Screen analysis took {time.time() - start_time:.3f}s")
        return context

    async def _run_ocr(self, capture: ScreenCapture) -> Dict:
        """Run OCR on screen capture."""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self._ocr_manager.extract_text, capture.image_data)

    async def _run_detection(self, capture: ScreenCapture) -> List[Detection]:
        """Run object detection on screen capture."""
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None, self._object_detector.detect, capture.image_data
        )
        return result.detections if result else []

    def _build_ui_elements(
        self,
        ocr_result: Dict,
        detections: List[Detection],
        capture: ScreenCapture
    ) -> List[UIElement]:
        """Build UI elements from OCR and detection results."""
        elements = []

        # Process OCR results - each text block is a potential UI element
        if "detailed" in ocr_result:
            for item in ocr_result["detailed"]:
                if item.get("confidence", 0) > 30:  # Filter low confidence
                    element = self._ocr_item_to_element(item)
                    if element:
                        elements.append(element)

        # Process YOLO detections
        for det in detections:
            element = self._detection_to_element(det)
            if element:
                elements.append(element)

        # Merge overlapping elements
        elements = self._merge_overlapping_elements(elements)

        # Classify element types based on visual properties
        elements = self._classify_elements(elements, capture)

        return elements

    def _ocr_item_to_element(self, item: Dict) -> Optional[UIElement]:
        """Convert OCR item to UI element."""
        try:
            x, y, w, h = item["x"], item["y"], item["w"], item["h"]
            text = item.get("text", "").strip()
            conf = item.get("confidence", 0)

            if not text and conf < 50:
                return None

            return UIElement(
                element_id=f"ocr_{hash(text + str(x) + str(y))}",
                element_type=UIElementType.TEXT,
                bounds=(x, y, w, h),
                text=text,
                confidence=conf / 100.0,
                attributes={"source": "ocr"},
            )
        except Exception:
            return None

    def _detection_to_element(self, det: Detection) -> Optional[UIElement]:
        """Convert YOLO detection to UI element."""
        try:
            x1, y1, x2, y2 = map(int, det.bbox)
            w, h = x2 - x1, y2 - y1

            # Map YOLO classes to UI element types
            type_map = {
                "button": UIElementType.BUTTON,
                "link": UIElementType.LINK,
                "input": UIElementType.TEXT_FIELD,
                "image": UIElementType.IMAGE,
                "icon": UIElementType.ICON,
            }

            element_type = type_map.get(det.class_name.lower(), UIElementType.UNKNOWN)

            return UIElement(
                element_id=f"det_{det.class_name}_{x1}_{y1}",
                element_type=element_type,
                bounds=(x1, y1, w, h),
                text="",
                confidence=det.confidence,
                attributes={"source": "yolo", "class": det.class_name},
            )
        except Exception:
            return None

    def _merge_overlapping_elements(self, elements: List[UIElement], iou_threshold: float = 0.5) -> List[UIElement]:
        """Merge overlapping elements."""
        if not elements:
            return []

        # Sort by confidence descending
        elements.sort(key=lambda e: e.confidence, reverse=True)

        merged = []
        for elem in elements:
            should_merge = False
            for existing in merged:
                if self._calculate_iou(elem.bounds, existing.bounds) > iou_threshold:
                    # Merge: keep higher confidence, combine text
                    if elem.confidence > existing.confidence:
                        existing.text = elem.text or existing.text
                        existing.confidence = elem.confidence
                        existing.attributes.update(elem.attributes)
                    else:
                        elem.text = existing.text or elem.text
                    should_merge = True
                    break

            if not should_merge:
                merged.append(elem)

        return merged

    def _calculate_iou(self, box1: Tuple, box2: Tuple) -> float:
        """Calculate Intersection over Union."""
        x1, y1, w1, h1 = box1
        x2, y2, w2, h2 = box2

        # Intersection
        xi1 = max(x1, x2)
        yi1 = max(y1, y2)
        xi2 = min(x1 + w1, x2 + w2)
        yi2 = min(y1 + h1, y2 + h2)

        if xi2 <= xi1 or yi2 <= yi1:
            return 0.0

        inter_area = (xi2 - xi1) * (yi2 - yi1)
        box1_area = w1 * h1
        box2_area = w2 * h2
        union_area = box1_area + box2_area - inter_area

        return inter_area / union_area if union_area > 0 else 0.0

    def _classify_elements(self, elements: List[UIElement], capture: ScreenCapture) -> List[UIElement]:
        """Classify element types based on visual properties."""
        for elem in elements:
            if elem.element_type != UIElementType.UNKNOWN and elem.element_type != UIElementType.TEXT:
                continue

            # Heuristics for classification
            x, y, w, h = elem.bounds
            aspect_ratio = w / h if h > 0 else 0
            area = w * h

            # Button-like: rectangular, moderate size, often has text
            if elem.text and 30 < w < 300 and 20 < h < 80 and 0.5 < aspect_ratio < 10:
                elem.element_type = UIElementType.BUTTON

            # Text field: wide, short, often empty text
            elif (not elem.text or len(elem.text) < 3) and w > 150 and 20 < h < 50:
                elem.element_type = UIElementType.TEXT_FIELD

            # Link: text that looks like URL or underlined
            elif elem.text and ("http" in elem.text.lower() or ".com" in elem.text.lower()):
                elem.element_type = UIElementType.LINK

            # Icon: small, square-ish
            elif area < 1000 and 0.7 < aspect_ratio < 1.5:
                elem.element_type = UIElementType.ICON

        return elements

    async def _detect_active_window(self, elements: List[UIElement]) -> Tuple[Optional[str], Optional[str]]:
        """Detect active window and application from UI elements."""
        # Look for window title bars, menu bars
        for elem in elements:
            if elem.element_type == UIElementType.WINDOW and elem.text:
                return elem.text, None

        # Check for application names in menu bar area (top of screen)
        top_elements = [e for e in elements if e.bounds[1] < 50]
        for elem in top_elements:
            if elem.text and len(elem.text) > 2:
                return None, elem.text

        return None, None

    def _build_layout_structure(self, elements: List[UIElement]) -> Dict:
        """Build hierarchical layout structure."""
        # Simple grid-based layout analysis
        if not elements:
            return {}

        # Find containers (large elements that contain others)
        containers = []
        for elem in elements:
            contained = [e for e in elements if e != elem and self._contains(elem, e)]
            if len(contained) > 1:
                containers.append({
                    "element_id": elem.element_id,
                    "type": elem.element_type.value,
                    "bounds": elem.bounds,
                    "children": [c.element_id for c in contained],
                })

        return {
            "containers": containers,
            "total_elements": len(elements),
            "element_types": {
                t.value: len([e for e in elements if e.element_type == t])
                for t in UIElementType
            },
        }

    def _contains(self, container: UIElement, child: UIElement) -> bool:
        """Check if container contains child."""
        cx, cy, cw, ch = container.bounds
        x, y, w, h = child.bounds
        return cx <= x and cy <= y and x + w <= cx + cw and y + h <= cy + ch

    def _detect_changes(self, previous: ScreenContext, current_elements: List[UIElement]) -> List[Dict]:
        """Detect changes from previous screen context."""
        changes = []

        prev_elements = {e.element_id: e for e in previous.elements}
        curr_elements = {e.element_id: e for e in current_elements}

        # New elements
        for eid, elem in curr_elements.items():
            if eid not in prev_elements:
                changes.append({
                    "type": "added",
                    "element": elem.to_dict(),
                })

        # Removed elements
        for eid, elem in prev_elements.items():
            if eid not in curr_elements:
                changes.append({
                    "type": "removed",
                    "element_id": eid,
                })

        # Changed elements
        for eid, elem in curr_elements.items():
            if eid in prev_elements:
                prev = prev_elements[eid]
                if prev.text != elem.text or prev.bounds != elem.bounds:
                    changes.append({
                        "type": "changed",
                        "element_id": eid,
                        "old_text": prev.text,
                        "new_text": elem.text,
                        "old_bounds": prev.bounds,
                        "new_bounds": elem.bounds,
                    })

        return changes

    async def find_element(self, monitor: int, criteria: Dict) -> Optional[UIElement]:
        """Find element matching criteria."""
        context = await self.analyze_screen(monitor)

        # Text search
        if "text" in criteria:
            text = criteria["text"].lower()
            for elem in context.elements:
                if text in elem.text.lower():
                    return elem

        # Type search
        if "type" in criteria:
            elem_type = UIElementType(criteria["type"])
            matches = context.get_elements_by_type(elem_type)
            if matches:
                return matches[0]

        # Position search
        if "position" in criteria:
            x, y = criteria["position"]
            for elem in context.elements:
                if elem.contains_point(x, y):
                    return elem

        return None

    async def wait_for_element(self, monitor: int, criteria: Dict, timeout: float = 10.0) -> Optional[UIElement]:
        """Wait for element to appear."""
        start = time.time()
        while time.time() - start < timeout:
            elem = await self.find_element(monitor, criteria)
            if elem:
                return elem
            await asyncio.sleep(0.5)
        return None

    async def start_continuous_analysis(self, monitor: int = 0, interval: float = 1.0) -> None:
        """Start continuous screen analysis."""
        self._running = True
        while self._running:
            try:
                await self.analyze_screen(monitor)
            except Exception as e:
                logger.error(f"Continuous analysis error: {e}")
            await asyncio.sleep(interval)

    def stop_continuous_analysis(self) -> None:
        """Stop continuous analysis."""
        self._running = False


# Global instance
_screen_understanding: Optional[ScreenUnderstanding] = None


def get_screen_understanding() -> ScreenUnderstanding:
    """Get global screen understanding instance."""
    global _screen_understanding
    if _screen_understanding is None:
        _screen_understanding = ScreenUnderstanding()
    return _screen_understanding