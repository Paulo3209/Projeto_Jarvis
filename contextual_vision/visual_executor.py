"""
Visual Executor - Executes visual tasks based on screen/camera understanding.
Performs actions like clicking, typing, navigating based on visual context.
"""
from __future__ import annotations
import asyncio
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Tuple

from core.event_bus import EventBus, get_event_bus
from tools.automation_tools import click, type_text, hotkey, press_key, move_mouse
from contextual_vision.screen_understanding import get_screen_understanding, ScreenContext, UIElement, UIElementType

logger = logging.getLogger(__name__)


class VisualTaskType(Enum):
    """Types of visual tasks."""
    CLICK_ELEMENT = "click_element"
    TYPE_IN_ELEMENT = "type_in_element"
    FIND_AND_CLICK = "find_and_click"
    WAIT_FOR_ELEMENT = "wait_for_element"
    VERIFY_ELEMENT = "verify_element"
    SCROLL_TO_ELEMENT = "scroll_to_element"
    DRAG_DROP = "drag_drop"
    NAVIGATE_MENU = "navigate_menu"
    FILL_FORM = "fill_form"
    EXTRACT_DATA = "extract_data"
    TAKE_SCREENSHOT = "take_screenshot"
    COMPARE_SCREENS = "compare_screens"


class VisualActionType(Enum):
    """Types of visual actions."""
    CLICK = "click"
    DOUBLE_CLICK = "double_click"
    RIGHT_CLICK = "right_click"
    TYPE = "type"
    KEY_PRESS = "key_press"
    HOTKEY = "hotkey"
    MOVE = "move"
    DRAG = "drag"
    SCROLL = "scroll"
    WAIT = "wait"
    SCREENSHOT = "screenshot"


@dataclass
class VisualAction:
    """Single visual action."""
    action_id: str
    action_type: VisualActionType
    target: Optional[UIElement] = None
    coordinates: Optional[Tuple[int, int]] = None
    parameters: Dict = field(default_factory=dict)
    delay_after: float = 0.1
    retry_count: int = 3
    verify_success: bool = True


@dataclass
class VisualTask:
    """Visual task to execute."""
    task_id: str
    task_type: VisualTaskType
    description: str
    actions: List[VisualAction] = field(default_factory=list)
    context: Optional[ScreenContext] = None
    success_criteria: Dict = field(default_factory=dict)
    timeout: float = 30.0
    created_at: datetime = field(default_factory=datetime.now)
    status: str = "pending"
    result: Optional[Dict] = None


@dataclass
class ExecutionResult:
    """Result of visual task execution."""
    task_id: str
    success: bool
    actions_completed: int
    actions_failed: int
    error: Optional[str] = None
    duration: float = 0.0
    screenshots: List[str] = field(default_factory=list)
    extracted_data: Dict = field(default_factory=dict)


class VisualExecutor:
    """
    Executes visual tasks based on screen understanding.
    Plans and executes sequences of visual actions.
    """

    def __init__(self):
        self._screen_understanding = get_screen_understanding()
        self._event_bus: Optional[EventBus] = None
        self._running_tasks: Dict[str, VisualTask] = {}
        self._action_handlers: Dict[VisualActionType, Callable] = {}
        self._register_action_handlers()

    async def initialize(self) -> None:
        """Initialize executor."""
        self._event_bus = await get_event_bus()

    def _register_action_handlers(self) -> None:
        """Register action type handlers."""
        self._action_handlers = {
            VisualActionType.CLICK: self._execute_click,
            VisualActionType.DOUBLE_CLICK: self._execute_double_click,
            VisualActionType.RIGHT_CLICK: self._execute_right_click,
            VisualActionType.TYPE: self._execute_type,
            VisualActionType.KEY_PRESS: self._execute_key_press,
            VisualActionType.HOTKEY: self._execute_hotkey,
            VisualActionType.MOVE: self._execute_move,
            VisualActionType.DRAG: self._execute_drag,
            VisualActionType.SCROLL: self._execute_scroll,
            VisualActionType.WAIT: self._execute_wait,
            VisualActionType.SCREENSHOT: self._execute_screenshot,
        }

    async def execute_task(self, task: VisualTask) -> ExecutionResult:
        """Execute a visual task."""
        start_time = time.time()
        task.status = "running"
        self._running_tasks[task.task_id] = task

        result = ExecutionResult(
            task_id=task.task_id,
            success=False,
            actions_completed=0,
            actions_failed=0,
        )

        try:
            # Get initial screen context if not provided
            if not task.context:
                task.context = await self._screen_understanding.analyze_screen()

            # Resolve element references in actions
            await self._resolve_element_references(task)

            # Execute actions sequentially
            for i, action in enumerate(task.actions):
                if not self._running:
                    break

                action_result = await self._execute_action(action, task.context)

                if action_result.get("success"):
                    result.actions_completed += 1
                else:
                    result.actions_failed += 1
                    if not self._retry_action(action, task.context):
                        result.error = f"Action {i} failed: {action_result.get('error')}"
                        break

                # Verify if needed
                if action.verify_success and not await self._verify_action(action, task.context):
                    result.error = f"Action {i} verification failed"
                    break

                await asyncio.sleep(action.delay_after)

                # Update context after action
                task.context = await self._screen_understanding.analyze_screen()

            # Check success criteria
            if result.actions_failed == 0 and await self._check_success_criteria(task, task.context):
                result.success = True
                task.status = "completed"
            else:
                task.status = "failed"

        except Exception as e:
            result.error = f"Execution error: {type(e).__name__}: {e}"
            task.status = "error"
            logger.error(f"Task execution error: {e}")

        finally:
            result.duration = time.time() - start_time
            task.result = result.__dict__
            self._running_tasks.pop(task.task_id, None)

            # Emit event
            if self._event_bus:
                from core.event_bus import ToolCompletedEvent, ToolFailedEvent
                if result.success:
                    self._event_bus.emit(ToolCompletedEvent("visual_execute", result.__dict__, task.task_id, source="visual_executor"))
                else:
                    self._event_bus.emit(ToolFailedEvent("visual_execute", result.error or "Unknown error", task.task_id, source="visual_executor"))

        return result

    async def _resolve_element_references(self, task: VisualTask) -> None:
        """Resolve element references in actions."""
        for action in task.actions:
            if action.target is None and "element_criteria" in action.parameters:
                criteria = action.parameters["element_criteria"]
                element = await self._screen_understanding.find_element(
                    task.context.monitor if task.context else 0,
                    criteria
                )
                if element:
                    action.target = element

    async def _execute_action(self, action: VisualAction, context: ScreenContext) -> Dict:
        """Execute a single action."""
        handler = self._action_handlers.get(action.action_type)
        if not handler:
            return {"success": False, "error": f"No handler for {action.action_type}"}

        try:
            return await handler(action, context)
        except Exception as e:
            return {"success": False, "error": str(e)}

    def _retry_action(self, action: VisualAction, context: ScreenContext) -> bool:
        """Retry failed action."""
        for attempt in range(action.retry_count):
            logger.info(f"Retrying action {action.action_id} (attempt {attempt + 1})")
            result = asyncio.run(self._execute_action(action, context))
            if result.get("success"):
                return True
            time.sleep(0.5)
        return False

    async def _verify_action(self, action: VisualAction, context: ScreenContext) -> bool:
        """Verify action succeeded."""
        # Re-analyze screen and check if expected change occurred
        new_context = await self._screen_understanding.analyze_screen(context.monitor)

        # Check for expected changes
        if "expected_change" in action.parameters:
            expected = action.parameters["expected_change"]
            if expected == "element_gone" and action.target:
                # Element should no longer be found
                elem = await self._screen_understanding.find_element(context.monitor, {"text": action.target.text})
                return elem is None
            elif expected == "text_changed" and action.target:
                elem = await self._screen_understanding.find_element(context.monitor, {"element_id": action.target.element_id})
                return elem and elem.text != action.target.text

        return True

    async def _check_success_criteria(self, task: VisualTask, context: ScreenContext) -> bool:
        """Check if task success criteria are met."""
        criteria = task.success_criteria

        if "element_present" in criteria:
            elem = await self._screen_understanding.find_element(context.monitor, criteria["element_present"])
            if not elem:
                return False

        if "element_absent" in criteria:
            elem = await self._screen_understanding.find_element(context.monitor, criteria["element_absent"])
            if elem:
                return False

        if "text_contains" in criteria:
            if criteria["text_contains"] not in context.text_content:
                return False

        if "window_title" in criteria:
            if context.active_window != criteria["window_title"]:
                return False

        return True

    # Action handlers
    async def _execute_click(self, action: VisualAction, context: ScreenContext) -> Dict:
        """Execute click action."""
        if action.target:
            x, y = action.target.center
        elif action.coordinates:
            x, y = action.coordinates
        else:
            return {"success": False, "error": "No target or coordinates"}

        result = await move_mouse({"x": x, "y": y})
        if not result.get("success"):
            return result

        return await click({"x": x, "y": y})

    async def _execute_double_click(self, action: VisualAction, context: ScreenContext) -> Dict:
        """Execute double click."""
        result = await self._execute_click(action, context)
        if result.get("success"):
            await asyncio.sleep(0.1)
            return await self._execute_click(action, context)
        return result

    async def _execute_right_click(self, action: VisualAction, context: ScreenContext) -> Dict:
        """Execute right click."""
        if action.target:
            x, y = action.target.center
        elif action.coordinates:
            x, y = action.coordinates
        else:
            return {"success": False, "error": "No target or coordinates"}

        result = await move_mouse({"x": x, "y": y})
        if not result.get("success"):
            return result

        # Right click via automation tools
        import pyautogui
        try:
            pyautogui.rightClick(x, y)
            return {"success": True}
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def _execute_type(self, action: VisualAction, context: ScreenContext) -> Dict:
        """Execute type action."""
        text = action.parameters.get("text", "")
        if not text:
            return {"success": False, "error": "No text to type"}

        # Click target first if specified
        if action.target:
            click_result = await self._execute_click(action, context)
            if not click_result.get("success"):
                return click_result
            await asyncio.sleep(0.2)

        return await type_text({"text": text})

    async def _execute_key_press(self, action: VisualAction, context: ScreenContext) -> Dict:
        """Execute key press."""
        key = action.parameters.get("key", "")
        if not key:
            return {"success": False, "error": "No key specified"}

        return await press_key({"key": key})

    async def _execute_hotkey(self, action: VisualAction, context: ScreenContext) -> Dict:
        """Execute hotkey combination."""
        keys = action.parameters.get("keys", [])
        if not keys:
            return {"success": False, "error": "No keys specified"}

        return await hotkey({"keys": "+".join(keys)})

    async def _execute_move(self, action: VisualAction, context: ScreenContext) -> Dict:
        """Execute mouse move."""
        if action.target:
            x, y = action.target.center
        elif action.coordinates:
            x, y = action.coordinates
        else:
            return {"success": False, "error": "No target or coordinates"}

        return await move_mouse({"x": x, "y": y})

    async def _execute_drag(self, action: VisualAction, context: ScreenContext) -> Dict:
        """Execute drag action."""
        start = action.parameters.get("start")
        end = action.parameters.get("end")

        if not start or not end:
            return {"success": False, "error": "Start and end coordinates required"}

        from tools.automation_tools import drag
        return await drag({"start_x": start[0], "start_y": start[1], "end_x": end[0], "end_y": end[1]})

    async def _execute_scroll(self, action: VisualAction, context: ScreenContext) -> Dict:
        """Execute scroll action."""
        direction = action.parameters.get("direction", "down")
        amount = action.parameters.get("amount", 3)

        import pyautogui
        try:
            if direction == "up":
                pyautogui.scroll(amount)
            elif direction == "down":
                pyautogui.scroll(-amount)
            elif direction == "left":
                pyautogui.hscroll(-amount)
            elif direction == "right":
                pyautogui.hscroll(amount)
            return {"success": True}
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def _execute_wait(self, action: VisualAction, context: ScreenContext) -> Dict:
        """Execute wait action."""
        duration = action.parameters.get("duration", 1.0)
        await asyncio.sleep(duration)
        return {"success": True}

    async def _execute_screenshot(self, action: VisualAction, context: ScreenContext) -> Dict:
        """Execute screenshot action."""
        from tools.automation_tools import screenshot
        result = await screenshot({})
        if result.get("success"):
            result["screenshot_path"] = result.get("path")
        return result

    # High-level task creators
    def create_click_task(self, criteria: Dict, monitor: int = 0, description: str = "") -> VisualTask:
        """Create task to find and click element."""
        import secrets
        task = VisualTask(
            task_id=f"click_{secrets.token_hex(4)}",
            task_type=VisualTaskType.FIND_AND_CLICK,
            description=description or f"Click element matching {criteria}",
            actions=[
                VisualAction(
                    action_id=f"action_{secrets.token_hex(4)}",
                    action_type=VisualActionType.CLICK,
                    parameters={"element_criteria": criteria, "expected_change": "element_gone"},
                )
            ],
            success_criteria={"element_absent": criteria},
        )
        return task

    def create_type_task(self, criteria: Dict, text: str, monitor: int = 0, description: str = "") -> VisualTask:
        """Create task to find element and type in it."""
        import secrets
        task = VisualTask(
            task_id=f"type_{secrets.token_hex(4)}",
            task_type=VisualTaskType.TYPE_IN_ELEMENT,
            description=description or f"Type in element matching {criteria}",
            actions=[
                VisualAction(
                    action_id=f"action_{secrets.token_hex(4)}",
                    action_type=VisualActionType.TYPE,
                    parameters={"element_criteria": criteria, "text": text, "expected_change": "text_changed"},
                )
            ],
            success_criteria={"element_present": criteria},
        )
        return task

    def create_form_fill_task(self, fields: List[Dict], monitor: int = 0) -> VisualTask:
        """Create task to fill form."""
        import secrets
        actions = []
        for field in fields:
            actions.append(VisualAction(
                action_id=f"action_{secrets.token_hex(4)}",
                action_type=VisualActionType.TYPE,
                parameters={
                    "element_criteria": field["criteria"],
                    "text": field["value"],
                    "expected_change": "text_changed",
                },
            ))

        task = VisualTask(
            task_id=f"form_{secrets.token_hex(4)}",
            task_type=VisualTaskType.FILL_FORM,
            description=f"Fill form with {len(fields)} fields",
            actions=actions,
        )
        return task

    async def execute_and_wait(self, task: VisualTask, poll_interval: float = 0.5) -> ExecutionResult:
        """Execute task and wait for completion."""
        return await self.execute_task(task)

    def cancel_task(self, task_id: str) -> bool:
        """Cancel running task."""
        if task_id in self._running_tasks:
            self._running_tasks[task_id].status = "cancelled"
            return True
        return False

    def get_running_tasks(self) -> List[VisualTask]:
        """Get list of running tasks."""
        return list(self._running_tasks.values())


# Global instance
_visual_executor: Optional[VisualExecutor] = None


async def get_visual_executor() -> VisualExecutor:
    """Get global visual executor instance."""
    global _visual_executor
    if _visual_executor is None:
        _visual_executor = VisualExecutor()
        await _visual_executor.initialize()
    return _visual_executor