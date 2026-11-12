"""
Camera Understanding - Real-time camera scene interpretation.
Uses object detection, scene classification, and activity recognition.
"""
from __future__ import annotations
import asyncio
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

import cv2
import numpy as np

from vision.camera import get_camera_manager, CameraFrame
from vision.detector import get_object_detector, get_face_detector, Detection, DetectionResult

logger = logging.getLogger(__name__)


class SceneCategory(Enum):
    """Scene categories."""
    INDOOR = "indoor"
    OUTDOOR = "outdoor"
    OFFICE = "office"
    HOME = "home"
    KITCHEN = "kitchen"
    LIVING_ROOM = "living_room"
    BEDROOM = "bedroom"
    BATHROOM = "bathroom"
    MEETING_ROOM = "meeting_room"
    STREET = "street"
    NATURE = "nature"
    VEHICLE = "vehicle"
    UNKNOWN = "unknown"


class ActivityType(Enum):
    """Detected activity types."""
    PERSON_WORKING = "person_working"
    PERSON_TALKING = "person_talking"
    PERSON_EATING = "person_eating"
    PERSON_READING = "person_reading"
    PERSON_SLEEPING = "person_sleeping"
    PERSON_EXERCISING = "person_exercising"
    MULTIPLE_PEOPLE = "multiple_people"
    NO_ACTIVITY = "no_activity"
    UNKNOWN = "unknown"


@dataclass
class DetectedObject:
    """Object detected in camera frame."""
    object_id: str
    class_name: str
    confidence: float
    bounds: Tuple[int, int, int, int]  # x, y, w, h
    attributes: Dict = field(default_factory=dict)
    tracker_id: Optional[int] = None

    @property
    def center(self) -> Tuple[int, int]:
        x, y, w, h = self.bounds
        return (x + w // 2, y + h // 2)


@dataclass
class FaceInfo:
    """Face detection info."""
    face_id: str
    bounds: Tuple[int, int, int, int]
    confidence: float
    landmarks: Optional[List[Tuple[int, int]]] = None
    estimated_age: Optional[int] = None
    estimated_gender: Optional[str] = None
    emotion: Optional[str] = None
    recognized: bool = False
    person_id: Optional[str] = None


@dataclass
class SceneDescription:
    """Complete scene description."""
    timestamp: datetime
    camera_id: str
    resolution: Tuple[int, int]
    objects: List[DetectedObject]
    faces: List[FaceInfo]
    scene_category: SceneCategory
    activity: ActivityType
    description: str
    confidence: float
    lighting: str  # bright, dim, dark
    motion_level: float  # 0-1

    def get_objects_by_class(self, class_name: str) -> List[DetectedObject]:
        return [o for o in self.objects if o.class_name.lower() == class_name.lower()]

    def get_people(self) -> List[DetectedObject]:
        return [o for o in self.objects if o.class_name.lower() == "person"]

    def to_dict(self) -> Dict:
        return {
            "timestamp": self.timestamp.isoformat(),
            "camera_id": self.camera_id,
            "resolution": self.resolution,
            "objects": [
                {
                    "object_id": o.object_id,
                    "class": o.class_name,
                    "confidence": o.confidence,
                    "bounds": o.bounds,
                    "center": o.center,
                }
                for o in self.objects
            ],
            "faces": [
                {
                    "face_id": f.face_id,
                    "bounds": f.bounds,
                    "confidence": f.confidence,
                    "emotion": f.emotion,
                    "recognized": f.recognized,
                    "person_id": f.person_id,
                }
                for f in self.faces
            ],
            "scene_category": self.scene_category.value,
            "activity": self.activity.value,
            "description": self.description,
            "confidence": self.confidence,
            "lighting": self.lighting,
            "motion_level": self.motion_level,
        }


@dataclass
class CameraContext:
    """Camera understanding context with history."""
    camera_id: str
    current_scene: Optional[SceneDescription] = None
    scene_history: List[SceneDescription] = field(default_factory=list)
    tracked_objects: Dict[str, DetectedObject] = field(default_factory=dict)
    known_faces: Dict[str, FaceInfo] = field(default_factory=dict)
    alerts: List[Dict] = field(default_factory=list)

    def add_scene(self, scene: SceneDescription) -> None:
        """Add scene to history."""
        self.scene_history.append(scene)
        self.current_scene = scene

        # Keep history limited
        if len(self.scene_history) > 100:
            self.scene_history = self.scene_history[-100:]

        # Update tracked objects
        for obj in scene.objects:
            self.tracked_objects[obj.object_id] = obj

        # Update known faces
        for face in scene.faces:
            if face.person_id:
                self.known_faces[face.person_id] = face

    def get_recent_scenes(self, seconds: float = 60) -> List[SceneDescription]:
        """Get scenes from last N seconds."""
        cutoff = datetime.now().timestamp() - seconds
        return [s for s in self.scene_history if s.timestamp.timestamp() > cutoff]

    def detect_changes(self, previous: SceneDescription) -> List[Dict]:
        """Detect changes between scenes."""
        changes = []

        if not previous or not self.current_scene:
            return changes

        # Object changes
        prev_objects = {o.object_id: o for o in previous.objects}
        curr_objects = {o.object_id: o for o in self.current_scene.objects}

        for oid, obj in curr_objects.items():
            if oid not in prev_objects:
                changes.append({"type": "object_appeared", "object": obj.class_name, "bounds": obj.bounds})
            elif prev_objects[oid].bounds != obj.bounds:
                changes.append({"type": "object_moved", "object": obj.class_name, "from": prev_objects[oid].bounds, "to": obj.bounds})

        for oid in prev_objects:
            if oid not in curr_objects:
                changes.append({"type": "object_disappeared", "object": prev_objects[oid].class_name})

        # Face changes
        if len(previous.faces) != len(self.current_scene.faces):
            changes.append({"type": "face_count_changed", "from": len(previous.faces), "to": len(self.current_scene.faces)})

        # Scene category change
        if previous.scene_category != self.current_scene.scene_category:
            changes.append({"type": "scene_changed", "from": previous.scene_category.value, "to": self.current_scene.scene_category.value})

        # Activity change
        if previous.activity != self.current_scene.activity:
            changes.append({"type": "activity_changed", "from": previous.activity.value, "to": self.current_scene.activity.value})

        return changes


class CameraUnderstanding:
    """
    Real-time camera scene understanding.
    Combines object detection, face recognition, scene classification, and activity recognition.
    """

    def __init__(self):
        self._camera_manager = get_camera_manager()
        self._object_detector = get_object_detector()
        self._face_detector = get_face_detector()
        self._contexts: Dict[str, CameraContext] = {}
        self._running = False
        self._callbacks: List[callable] = []
        self._previous_frame: Optional[np.ndarray] = None

    def add_callback(self, callback: callable) -> None:
        """Add callback for camera context updates."""
        self._callbacks.append(callback)

    async def analyze_camera(self, camera_id: str = "0", camera_index: int = 0) -> SceneDescription:
        """Analyze current camera frame."""
        start_time = time.time()

        # Capture frame
        frame = await self._camera_manager.capture(camera_index=camera_index)
        if not frame:
            return self._empty_scene(camera_id, "No frame captured")

        # Run detections in parallel
        detect_task = asyncio.create_task(self._run_object_detection(frame))
        face_task = asyncio.create_task(self._run_face_detection(frame))

        detections, faces = await asyncio.gather(detect_task, face_task)

        # Classify scene
        scene_category = self._classify_scene(detections)

        # Recognize activity
        activity = self._recognize_activity(detections, faces)

        # Assess lighting
        lighting = self._assess_lighting(frame.image_data)

        # Detect motion
        motion_level = self._detect_motion(frame.image_data)

        # Generate description
        description = self._generate_description(detections, faces, scene_category, activity)

        # Build detected objects
        objects = [
            DetectedObject(
                object_id=f"obj_{det.class_name}_{det.bbox[0]}_{det.bbox[1]}",
                class_name=det.class_name,
                confidence=det.confidence,
                bounds=(int(det.bbox[0]), int(det.bbox[1]), int(det.bbox[2] - det.bbox[0]), int(det.bbox[3] - det.bbox[1])),
            )
            for det in detections
        ]

        # Build face info
        face_infos = [
            FaceInfo(
                face_id=f"face_{i}",
                bounds=(int(f.bbox[0]), int(f.bbox[1]), int(f.bbox[2] - f.bbox[0]), int(f.bbox[3] - f.bbox[1])),
                confidence=f.confidence,
            )
            for i, f in enumerate(faces)
        ]

        scene = SceneDescription(
            timestamp=datetime.now(),
            camera_id=camera_id,
            resolution=(frame.width, frame.height),
            objects=objects,
            faces=face_infos,
            scene_category=scene_category,
            activity=activity,
            description=description,
            confidence=min(1.0, np.mean([d.confidence for d in detections]) if detections else 0.5),
            lighting=lighting,
            motion_level=motion_level,
        )

        # Update context
        if camera_id not in self._contexts:
            self._contexts[camera_id] = CameraContext(camera_id=camera_id)
        self._contexts[camera_id].add_scene(scene)

        # Detect changes
        if len(self._contexts[camera_id].scene_history) > 1:
            prev = self._contexts[camera_id].scene_history[-2]
            changes = self._contexts[camera_id].detect_changes(prev)
            if changes:
                scene.__dict__["changes"] = changes

        # Notify callbacks
        for callback in self._callbacks:
            try:
                await callback(scene)
            except Exception as e:
                logger.error(f"Callback error: {e}")

        logger.debug(f"Camera analysis took {time.time() - start_time:.3f}s")
        return scene

    def _empty_scene(self, camera_id: str, reason: str) -> SceneDescription:
        return SceneDescription(
            timestamp=datetime.now(),
            camera_id=camera_id,
            resolution=(0, 0),
            objects=[],
            faces=[],
            scene_category=SceneCategory.UNKNOWN,
            activity=ActivityType.NO_ACTIVITY,
            description=reason,
            confidence=0.0,
            lighting="unknown",
            motion_level=0.0,
        )

    async def _run_object_detection(self, frame: CameraFrame) -> List[Detection]:
        """Run object detection on frame."""
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None, self._object_detector.detect, frame.image_data
        )
        return result.detections if result else []

    async def _run_face_detection(self, frame: CameraFrame) -> List[Detection]:
        """Run face detection on frame."""
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None, self._face_detector.detect, frame.image_data
        )
        return result.detections if result else []

    def _classify_scene(self, detections: List[Detection]) -> SceneCategory:
        """Classify scene based on detected objects."""
        if not detections:
            return SceneCategory.UNKNOWN

        classes = [d.class_name.lower() for d in detections]

        # Simple rule-based classification
        if "person" in classes and "laptop" in classes:
            return SceneCategory.OFFICE
        elif "person" in classes and ("bed" in classes or "pillow" in classes):
            return SceneCategory.BEDROOM
        elif "person" in classes and ("tv" in classes or "sofa" in classes or "couch" in classes):
            return SceneCategory.LIVING_ROOM
        elif "person" in classes and ("refrigerator" in classes or "oven" in classes or "microwave" in classes):
            return SceneCategory.KITCHEN
        elif "car" in classes or "truck" in classes or "bus" in classes:
            return SceneCategory.VEHICLE
        elif "person" in classes and "chair" in classes and "dining table" in classes:
            return SceneCategory.MEETING_ROOM
        elif "tree" in classes or "sky" in classes or "grass" in classes:
            return SceneCategory.NATURE
        elif "person" in classes:
            return SceneCategory.INDOOR
        else:
            return SceneCategory.OUTDOOR

    def _recognize_activity(self, detections: List[Detection], faces: List[Detection]) -> ActivityType:
        """Recognize activity from detections."""
        classes = [d.class_name.lower() for d in detections]
        person_count = classes.count("person")

        if person_count == 0:
            return ActivityType.NO_ACTIVITY
        elif person_count > 1:
            return ActivityType.MULTIPLE_PEOPLE
        elif "laptop" in classes or "keyboard" in classes or "mouse" in classes:
            return ActivityType.PERSON_WORKING
        elif "cell phone" in classes:
            return ActivityType.PERSON_TALKING
        elif "book" in classes:
            return ActivityType.PERSON_READING
        elif "fork" in classes or "knife" in classes or "spoon" in classes or "cup" in classes:
            return ActivityType.PERSON_EATING
        elif "bed" in classes and person_count == 1:
            return ActivityType.PERSON_SLEEPING
        elif "sports ball" in classes or "tennis racket" in classes:
            return ActivityType.PERSON_EXERCISING
        else:
            return ActivityType.UNKNOWN

    def _assess_lighting(self, image: np.ndarray) -> str:
        """Assess lighting conditions."""
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        mean_brightness = np.mean(gray)

        if mean_brightness > 180:
            return "bright"
        elif mean_brightness > 80:
            return "normal"
        elif mean_brightness > 30:
            return "dim"
        else:
            return "dark"

    def _detect_motion(self, image: np.ndarray) -> float:
        """Detect motion level compared to previous frame."""
        if self._previous_frame is None:
            self._previous_frame = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
            return 0.0

        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        diff = cv2.absdiff(self._previous_frame, gray)
        motion = np.mean(diff) / 255.0
        self._previous_frame = gray
        return min(1.0, motion * 5)  # Scale up

    def _generate_description(
        self,
        detections: List[Detection],
        faces: List[Detection],
        scene: SceneCategory,
        activity: ActivityType,
    ) -> str:
        """Generate natural language description."""
        parts = []

        # Scene
        parts.append(f"Scene appears to be {scene.value.replace('_', ' ')}")

        # Objects
        if detections:
            obj_counts = {}
            for d in detections:
                obj_counts[d.class_name] = obj_counts.get(d.class_name, 0) + 1

            obj_descs = []
            for cls, count in sorted(obj_counts.items(), key=lambda x: -x[1])[:5]:
                if count == 1:
                    obj_descs.append(f"a {cls}")
                else:
                    obj_descs.append(f"{count} {cls}s")

            if obj_descs:
                parts.append(f"with {', '.join(obj_descs)} detected")

        # Faces
        if faces:
            parts.append(f"{len(faces)} face{'s' if len(faces) > 1 else ''} detected")

        # Activity
        if activity != ActivityType.UNKNOWN and activity != ActivityType.NO_ACTIVITY:
            parts.append(f"Activity: {activity.value.replace('_', ' ')}")

        return ". ".join(parts) + "."

    def get_context(self, camera_id: str) -> Optional[CameraContext]:
        """Get camera context."""
        return self._contexts.get(camera_id)

    async def start_continuous_analysis(self, camera_id: str = "0", camera_index: int = 0, interval: float = 1.0) -> None:
        """Start continuous camera analysis."""
        self._running = True
        while self._running:
            try:
                await self.analyze_camera(camera_id, camera_index)
            except Exception as e:
                logger.error(f"Continuous camera analysis error: {e}")
            await asyncio.sleep(interval)

    def stop_continuous_analysis(self) -> None:
        """Stop continuous analysis."""
        self._running = False


# Global instance
_camera_understanding: Optional[CameraUnderstanding] = None


def get_camera_understanding() -> CameraUnderstanding:
    """Get global camera understanding instance."""
    global _camera_understanding
    if _camera_understanding is None:
        _camera_understanding = CameraUnderstanding()
    return _camera_understanding