"""
Context Fusion - Fuses screen and camera understanding for complete situational awareness.
Combines visual contexts from multiple sources for intelligent decision making.
"""
from __future__ import annotations
import asyncio
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, Callable

from contextual_vision.screen_understanding import get_screen_understanding, ScreenContext
from contextual_vision.camera_understanding import get_camera_understanding, CameraContext, SceneDescription

logger = logging.getLogger(__name__)


@dataclass
class FusedContext:
    """Fused context from screen and camera."""
    timestamp: datetime
    screen_context: Optional[ScreenContext] = None
    camera_contexts: Dict[str, CameraContext] = field(default_factory=dict)
    current_scene: Optional[SceneDescription] = None
    user_activity: str = "unknown"
    attention_focus: Optional[str] = None  # "screen", "camera:N", "away"
    context_confidence: float = 0.0
    anomalies: List[Dict] = field(default_factory=list)
    suggestions: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict:
        return {
            "timestamp": self.timestamp.isoformat(),
            "has_screen": self.screen_context is not None,
            "cameras": list(self.camera_contexts.keys()),
            "user_activity": self.user_activity,
            "attention_focus": self.attention_focus,
            "confidence": self.context_confidence,
            "anomalies": self.anomalies,
            "suggestions": self.suggestions,
        }


class ContextFusion:
    """
    Fuses screen and camera understanding for complete situational awareness.
    """

    def __init__(self):
        self._screen_understanding = get_screen_understanding()
        self._camera_understanding = get_camera_understanding()
        self._fused_context: Optional[FusedContext] = None
        self._running = False
        self._callbacks: List[Callable] = []
        self._screen_interval = 1.0
        self._camera_interval = 2.0
        self._fusion_interval = 0.5

    def add_callback(self, callback: Callable) -> None:
        """Add callback for fused context updates."""
        self._callbacks.append(callback)

    async def fuse_once(
        self,
        monitor: int = 0,
        camera_indices: List[int] = None,
    ) -> FusedContext:
        """Perform one fusion cycle."""
        camera_indices = camera_indices or [0]

        # Capture screen and camera in parallel
        screen_task = asyncio.create_task(self._screen_understanding.analyze_screen(monitor))
        camera_tasks = [
            asyncio.create_task(self._camera_understanding.analyze_camera(f"cam_{i}", i))
            for i in camera_indices
        ]

        screen_context, *camera_scenes = await asyncio.gather(screen_task, *camera_tasks)

        # Build camera contexts
        camera_contexts = {}
        for i, scene in enumerate(camera_scenes):
            cam_id = f"cam_{camera_indices[i]}"
            if cam_id not in self._camera_understanding._contexts:
                self._camera_understanding._contexts[cam_id] = self._camera_understanding._contexts.get(
                    cam_id,
                    self._camera_understanding._contexts.get(cam_id)
                )
            camera_contexts[cam_id] = self._camera_understanding._contexts[cam_id]

        # Fuse contexts
        fused = self._fuse_contexts(screen_context, camera_contexts)

        self._fused_context = fused

        # Notify callbacks
        for callback in self._callbacks:
            try:
                await callback(fused)
            except Exception as e:
                logger.error(f"Fusion callback error: {e}")

        return fused

    def _fuse_contexts(
        self,
        screen: ScreenContext,
        cameras: Dict[str, CameraContext],
    ) -> FusedContext:
        """Fuse screen and camera contexts."""
        fused = FusedContext(
            timestamp=datetime.now(),
            screen_context=screen,
            camera_contexts=cameras,
        )

        # Determine current scene (most recent camera)
        latest_scene = None
        latest_time = 0
        for cam_id, ctx in cameras.items():
            if ctx.current_scene and ctx.current_scene.timestamp.timestamp() > latest_time:
                latest_time = ctx.current_scene.timestamp.timestamp()
                latest_scene = ctx.current_scene

        fused.current_scene = latest_scene

        # Infer user activity
        fused.user_activity = self._infer_activity(screen, cameras)
        fused.attention_focus = self._infer_attention(screen, cameras)
        fused.context_confidence = self._calculate_confidence(screen, cameras)
        fused.anomalies = self._detect_anomalies(screen, cameras)
        fused.suggestions = self._generate_suggestions(fused)

        return fused

    def _infer_activity(
        self,
        screen: ScreenContext,
        cameras: Dict[str, CameraContext],
    ) -> str:
        """Infer user activity from contexts."""
        # Screen-based activity
        if screen.application:
            app = screen.application.lower()
            if any(kw in app for kw in ["code", "editor", "ide", "vim", "vscode"]):
                return "coding"
            elif any(kw in app for kw in ["browser", "chrome", "firefox", "edge"]):
                return "browsing"
            elif any(kw in app for kw in ["word", "writer", "docs"]):
                return "writing"
            elif any(kw in app for kw in ["excel", "sheets", "calc"]):
                return "spreadsheet"
            elif any(kw in app for kw in ["powerpoint", "slides", "keynote"]):
                return "presentation"
            elif any(kw in app for kw in ["terminal", "cmd", "powershell", "bash"]):
                return "terminal"
            elif any(kw in app for kw in ["discord", "slack", "teams", "zoom"]):
                return "meeting"
            elif any(kw in app for kw in ["spotify", "music", "media"]):
                return "media"

        # Camera-based activity
        for cam_id, ctx in cameras.items():
            if ctx.current_scene:
                activity = ctx.current_scene.activity.value
                if activity != "no_activity" and activity != "unknown":
                    return f"camera:{activity}"

        # Screen text analysis
        text = screen.text_content.lower()
        if any(kw in text for kw in ["error", "exception", "failed", "bug"]):
            return "debugging"
        elif any(kw in text for kw in ["password", "login", "sign in", "auth"]):
            return "authentication"

        return "general"

    def _infer_attention(
        self,
        screen: ScreenContext,
        cameras: Dict[str, CameraContext],
    ) -> str:
        """Infer where user's attention is focused."""
        # Check camera for face looking at screen
        for cam_id, ctx in cameras.items():
            if ctx.current_scene:
                scene = ctx.current_scene
                # If person detected and scene is office/meeting room
                if scene.activity.value in ["person_working", "person_reading"]:
                    if scene.scene_category in [scene.scene_category.OFFICE, scene.scene_category.MEETING_ROOM]:
                        return "screen"

                # If person detected but not working
                if scene.activity.value in ["person_talking", "person_eating"]:
                    return f"camera:{cam_id}"

        # Default to screen if active
        if screen.active_window:
            return "screen"

        return "away"

    def _calculate_confidence(
        self,
        screen: ScreenContext,
        cameras: Dict[str, CameraContext],
    ) -> float:
        """Calculate confidence in fused context."""
        confidences = []

        if screen.elements:
            confidences.append(0.8)

        for cam_id, ctx in cameras.items():
            if ctx.current_scene:
                confidences.append(ctx.current_scene.confidence)

        return sum(confidences) / len(confidences) if confidences else 0.0

    def _detect_anomalies(
        self,
        screen: ScreenContext,
        cameras: Dict[str, CameraContext],
    ) -> List[Dict]:
        """Detect anomalies in context."""
        anomalies = []

        # Screen changed but no camera activity
        if screen.changes_from_previous:
            has_person = any(
                ctx.current_scene and ctx.current_scene.activity.value != "no_activity"
                for ctx in cameras.values()
            )
            if not has_person:
                anomalies.append({
                    "type": "screen_change_without_presence",
                    "description": "Screen changed but no person detected",
                    "severity": "info",
                })

        # Camera detects person but screen inactive
        for cam_id, ctx in cameras.items():
            if ctx.current_scene and ctx.current_scene.activity.value in ["person_working", "person_reading"]:
                if not screen.active_window and len(screen.elements) < 10:
                    anomalies.append({
                        "type": "person_working_no_screen_activity",
                        "camera": cam_id,
                        "description": "Person appears to be working but screen shows little activity",
                        "severity": "warning",
                    })

        # Multiple people detected
        for cam_id, ctx in cameras.items():
            if ctx.current_scene:
                people = ctx.current_scene.get_people()
                if len(people) > 1:
                    anomalies.append({
                        "type": "multiple_people",
                        "camera": cam_id,
                        "count": len(people),
                        "severity": "info",
                    })

        return anomalies

    def _generate_suggestions(self, fused: FusedContext) -> List[str]:
        """Generate contextual suggestions."""
        suggestions = []

        # Based on activity
        if fused.user_activity == "coding":
            suggestions.append("Need help with code? I can explain, debug, or refactor.")
        elif fused.user_activity == "debugging":
            suggestions.append("I can help analyze errors or suggest fixes.")
        elif fused.user_activity == "meeting":
            suggestions.append("In a meeting? I can take notes or set reminders.")
        elif fused.user_activity == "writing":
            suggestions.append("Writing? I can help with grammar, style, or ideas.")

        # Based on anomalies
        for anomaly in fused.anomalies:
            if anomaly["type"] == "person_working_no_screen_activity":
                suggestions.append("You seem focused - need me to minimize distractions?")
            elif anomaly["type"] == "multiple_people":
                suggestions.append("Multiple people detected - switching to presentation mode?")

        # Based on attention
        if fused.attention_focus and fused.attention_focus.startswith("camera"):
            suggestions.append("You're away from screen - want me to read notifications aloud?")

        return suggestions[:3]  # Limit to 3 suggestions

    async def start_continuous_fusion(
        self,
        monitor: int = 0,
        camera_indices: List[int] = None,
    ) -> None:
        """Start continuous context fusion."""
        self._running = True
        camera_indices = camera_indices or [0]

        screen_task = asyncio.create_task(self._continuous_screen(monitor))
        camera_tasks = [
            asyncio.create_task(self._continuous_camera(f"cam_{i}", i))
            for i in camera_indices
        ]
        fusion_task = asyncio.create_task(self._continuous_fusion())

        try:
            await asyncio.gather(screen_task, *camera_tasks, fusion_task)
        except asyncio.CancelledError:
            pass

    async def _continuous_screen(self, monitor: int) -> None:
        """Continuous screen analysis."""
        while self._running:
            try:
                await self._screen_understanding.analyze_screen(monitor)
            except Exception as e:
                logger.error(f"Continuous screen error: {e}")
            await asyncio.sleep(self._screen_interval)

    async def _continuous_camera(self, cam_id: str, camera_index: int) -> None:
        """Continuous camera analysis."""
        while self._running:
            try:
                await self._camera_understanding.analyze_camera(cam_id, camera_index)
            except Exception as e:
                logger.error(f"Continuous camera error: {e}")
            await asyncio.sleep(self._camera_interval)

    async def _continuous_fusion(self) -> None:
        """Continuous fusion."""
        while self._running:
            try:
                await self.fuse_once()
            except Exception as e:
                logger.error(f"Continuous fusion error: {e}")
            await asyncio.sleep(self._fusion_interval)

    def stop(self) -> None:
        """Stop continuous fusion."""
        self._running = False

    def get_current_context(self) -> Optional[FusedContext]:
        """Get current fused context."""
        return self._fused_context


# Global instance
_context_fusion: Optional[ContextFusion] = None


def get_context_fusion() -> ContextFusion:
    """Get global context fusion instance."""
    global _context_fusion
    if _context_fusion is None:
        _context_fusion = ContextFusion()
    return _context_fusion