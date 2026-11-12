"""
Planner Agent - Task planning and decomposition for JARVIS.
Breaks complex requests into executable steps with dependencies.
"""
from __future__ import annotations
import asyncio
import json
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional, Callable
from pathlib import Path

logger = logging.getLogger(__name__)


class StepStatus(Enum):
    """Step execution status."""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"
    WAITING_APPROVAL = "waiting_approval"


class StepType(Enum):
    """Type of step."""
    TOOL_CALL = "tool_call"
    CONDITION = "condition"
    LOOP = "loop"
    PARALLEL = "parallel"
    USER_INPUT = "user_input"
    WAIT = "wait"


@dataclass
class PlanStep:
    """Single step in a plan."""
    id: str
    name: str
    type: StepType
    description: str
    tool_name: Optional[str] = None
    tool_args: Dict = field(default_factory=dict)
    condition: Optional[str] = None  # For conditional steps
    depends_on: List[str] = field(default_factory=list)  # Step IDs this depends on
    status: StepStatus = StepStatus.PENDING
    result: Optional[Dict] = None
    error: Optional[str] = None
    retry_count: int = 0
    max_retries: int = 3
    timeout: float = 30.0
    requires_approval: bool = False
    approval_reason: str = ""


@dataclass
class Plan:
    """Complete execution plan."""
    id: str
    goal: str
    steps: List[PlanStep] = field(default_factory=list)
    created_at: datetime = field(default_factory=datetime.now)
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    status: str = "created"  # created, running, completed, failed, paused
    metadata: Dict = field(default_factory=dict)

    def get_step(self, step_id: str) -> Optional[PlanStep]:
        """Get step by ID."""
        for step in self.steps:
            if step.id == step_id:
                return step
        return None

    def get_ready_steps(self) -> List[PlanStep]:
        """Get steps that are ready to execute (dependencies met)."""
        ready = []
        for step in self.steps:
            if step.status != StepStatus.PENDING:
                continue

            # Check dependencies
            deps_met = True
            for dep_id in step.depends_on:
                dep_step = self.get_step(dep_id)
                if not dep_step or dep_step.status != StepStatus.COMPLETED:
                    deps_met = False
                    break

            if deps_met:
                ready.append(step)

        return ready

    def is_complete(self) -> bool:
        """Check if all steps are completed."""
        return all(s.status in (StepStatus.COMPLETED, StepStatus.SKIPPED) for s in self.steps)

    def has_failures(self) -> bool:
        """Check if any step failed."""
        return any(s.status == StepStatus.FAILED for s in self.steps)

    def get_progress(self) -> Dict:
        """Get execution progress."""
        total = len(self.steps)
        completed = sum(1 for s in self.steps if s.status == StepStatus.COMPLETED)
        failed = sum(1 for s in self.steps if s.status == StepStatus.FAILED)
        running = sum(1 for s in self.steps if s.status == StepStatus.RUNNING)
        pending = sum(1 for s in self.steps if s.status == StepStatus.PENDING)

        return {
            "total": total,
            "completed": completed,
            "failed": failed,
            "running": running,
            "pending": pending,
            "percent": (completed / total * 100) if total > 0 else 0
        }


class Planner:
    """
    Plans complex tasks by decomposing them into steps.
    Uses LLM to generate plans from natural language goals.
    """

    def __init__(self, llm_client=None, available_tools: List[str] = None):
        self.llm_client = llm_client
        self.available_tools = available_tools or []
        self._plan_templates: Dict[str, List[Dict]] = {}
        self._load_templates()

    def _load_templates(self) -> None:
        """Load plan templates for common tasks."""
        self._plan_templates = {
            "prepare_work_environment": [
                {"name": "check_system", "tool": "get_system_info", "args": {}},
                {"name": "list_windows", "tool": "list_windows", "args": {}},
                {"name": "open_ide", "tool": "open_app", "args": {"app": "code"}},
                {"name": "open_terminal", "tool": "open_app", "args": {"app": "terminal"}},
                {"name": "open_browser", "tool": "open_website", "args": {"url": "https://github.com"}},
            ],
            "system_checkup": [
                {"name": "system_info", "tool": "get_system_info", "args": {}},
                {"name": "memory_check", "tool": "get_memory_info", "args": {}},
                {"name": "disk_check", "tool": "get_disk_usage", "args": {}},
                {"name": "network_check", "tool": "network_ping", "args": {"host": "8.8.8.8"}},
            ],
            "find_file": [
                {"name": "search_files", "tool": "search_files", "args": {"pattern": "{query}"}},
                {"name": "list_results", "tool": "list_files", "args": {"path": "{search_results[0].path}"}},
            ],
        }

    def create_plan_from_template(self, template_name: str, params: Dict = None) -> Plan:
        """Create plan from predefined template."""
        template = self._plan_templates.get(template_name)
        if not template:
            raise ValueError(f"Template not found: {template_name}")

        params = params or {}
        plan_id = str(uuid.uuid4())[:8]
        plan = Plan(id=plan_id, goal=f"Execute template: {template_name}")

        for i, step_tpl in enumerate(template):
            step_id = f"step_{i}"
            tool_name = step_tpl.get("tool")
            tool_args = step_tpl.get("args", {})

            # Substitute parameters
            for key, value in tool_args.items():
                if isinstance(value, str):
                    for pkey, pvalue in params.items():
                        value = value.replace(f"{{{pkey}}}", str(pvalue))
                    tool_args[key] = value

            step = PlanStep(
                id=step_id,
                name=step_tpl.get("name", f"Step {i+1}"),
                type=StepType.TOOL_CALL,
                description=f"Execute {tool_name}",
                tool_name=tool_name,
                tool_args=tool_args,
                depends_on=[f"step_{i-1}"] if i > 0 else []
            )
            plan.steps.append(step)

        return plan

    async def create_plan_from_goal(
        self,
        goal: str,
        context: Dict = None,
        max_steps: int = 10
    ) -> Plan:
        """
        Create plan from natural language goal using LLM.
        Falls back to template matching if no LLM.
        """
        if self.llm_client:
            return await self._create_plan_llm(goal, context, max_steps)
        else:
            return self._create_plan_heuristic(goal, context)

    async def _create_plan_llm(
        self,
        goal: str,
        context: Dict = None,
        max_steps: int = 10
    ) -> Plan:
        """Create plan using LLM."""
        # This would use the LLM to generate a plan
        # For now, fallback to heuristic
        return self._create_plan_heuristic(goal, context)

    def _create_plan_heuristic(self, goal: str, context: Dict = None) -> Plan:
        """Create plan using keyword matching."""
        goal_lower = goal.lower()
        plan_id = str(uuid.uuid4())[:8]
        plan = Plan(id=plan_id, goal=goal)

        # Simple keyword-based planning
        steps = []

        if any(kw in goal_lower for kw in ["ambiente", "trabalho", "work", "prepare", "setup"]):
            steps.extend(self._plan_templates.get("prepare_work_environment", []))

        if any(kw in goal_lower for kw in ["verificar", "check", "status", "saúde", "health"]):
            steps.extend(self._plan_templates.get("system_checkup", []))

        if any(kw in goal_lower for kw in ["encontrar", "buscar", "procurar", "find", "search"]):
            # Extract query
            query = goal
            for kw in ["encontrar", "buscar", "procurar", "find", "search"]:
                if kw in goal_lower:
                    query = goal.split(kw, 1)[-1].strip()
                    break
            tpl = self._plan_templates.get("find_file", [])
            for s in tpl:
                s = s.copy()
                s["args"] = {k: v.replace("{query}", query) for k, v in s.get("args", {}).items()}
                steps.append(s)

        if not steps:
            # Generic single-step plan
            steps.append({
                "name": "execute_goal",
                "tool": "generic_tool",
                "args": {"goal": goal}
            })

        for i, step_tpl in enumerate(steps[:max_steps]):
            step = PlanStep(
                id=f"step_{i}",
                name=step_tpl.get("name", f"Step {i+1}"),
                type=StepType.TOOL_CALL,
                description=f"Execute {step_tpl.get('tool', 'unknown')}",
                tool_name=step_tpl.get("tool"),
                tool_args=step_tpl.get("args", {}),
                depends_on=[f"step_{i-1}"] if i > 0 else []
            )
            plan.steps.append(step)

        return plan

    def add_template(self, name: str, steps: List[Dict]) -> None:
        """Add a new plan template."""
        self._plan_templates[name] = steps

    def get_templates(self) -> List[str]:
        """List available templates."""
        return list(self._plan_templates.keys())


class PlanExecutor:
    """
    Executes a plan step by step, handling dependencies, retries, and approvals.
    """

    def __init__(
        self,
        tool_registry: Callable[[str, Dict], Any],
        approval_callback: Callable[[PlanStep], bool] = None,
        progress_callback: Callable[[Plan, PlanStep], None] = None
    ):
        self.tool_registry = tool_registry
        self.approval_callback = approval_callback
        self.progress_callback = progress_callback
        self._current_plan: Optional[Plan] = None
        self._running = False
        self._paused = False
        self._cancel_requested = False

    async def execute(self, plan: Plan) -> Plan:
        """Execute a plan fully."""
        self._current_plan = plan
        self._running = True
        self._cancel_requested = False
        plan.status = "running"
        plan.started_at = datetime.now()

        logger.info(f"Starting plan execution: {plan.id} - {plan.goal}")

        while self._running and not plan.is_complete() and not plan.has_failures():
            if self._cancel_requested:
                plan.status = "cancelled"
                break

            if self._paused:
                await asyncio.sleep(0.5)
                continue

            ready_steps = plan.get_ready_steps()
            if not ready_steps:
                # No ready steps, check if waiting for approval
                waiting = [s for s in plan.steps if s.status == StepStatus.WAITING_APPROVAL]
                if waiting:
                    await asyncio.sleep(1.0)
                    continue
                # No ready steps and not waiting - might be deadlock
                logger.warning("No ready steps available, possible deadlock")
                break

            # Execute ready steps (can run in parallel if no dependencies between them)
            tasks = [self._execute_step(plan, step) for step in ready_steps]
            await asyncio.gather(*tasks)

        if plan.has_failures():
            plan.status = "failed"
        elif self._cancel_requested:
            plan.status = "cancelled"
        else:
            plan.status = "completed"

        plan.completed_at = datetime.now()
        self._running = False
        logger.info(f"Plan {plan.id} finished with status: {plan.status}")

        return plan

    async def _execute_step(self, plan: Plan, step: PlanStep) -> None:
        """Execute a single step."""
        step.status = StepStatus.RUNNING
        logger.info(f"Executing step: {step.name} ({step.id})")

        if self.progress_callback:
            self.progress_callback(plan, step)

        # Check approval
        if step.requires_approval:
            step.status = StepStatus.WAITING_APPROVAL
            if self.approval_callback:
                approved = self.approval_callback(step)
                if not approved:
                    step.status = StepStatus.FAILED
                    step.error = "User rejected approval"
                    return
            step.status = StepStatus.RUNNING

        try:
            # Execute with timeout
            if step.type == StepType.TOOL_CALL:
                result = await asyncio.wait_for(
                    self._call_tool(step.tool_name, step.tool_args),
                    timeout=step.timeout
                )
                step.result = result
                step.status = StepStatus.COMPLETED if result.get("success", False) else StepStatus.FAILED
                if not result.get("success", False):
                    step.error = result.get("error", "Tool returned failure")

            elif step.type == StepType.WAIT:
                await asyncio.sleep(step.tool_args.get("duration", 1.0))
                step.status = StepStatus.COMPLETED
                step.result = {"success": True, "message": "Wait completed"}

            else:
                step.status = StepStatus.FAILED
                step.error = f"Unsupported step type: {step.type}"

        except asyncio.TimeoutError:
            step.status = StepStatus.FAILED
            step.error = f"Step timed out after {step.timeout}s"
        except Exception as e:
            step.status = StepStatus.FAILED
            step.error = f"Execution error: {e}"
            logger.error(f"Step {step.id} failed: {e}")

        # Retry logic
        if step.status == StepStatus.FAILED and step.retry_count < step.max_retries:
            step.retry_count += 1
            step.status = StepStatus.PENDING
            logger.info(f"Retrying step {step.id} (attempt {step.retry_count}/{step.max_retries})")
            await asyncio.sleep(1.0 * step.retry_count)  # Exponential backoff

    async def _call_tool(self, tool_name: str, args: Dict) -> Dict:
        """Call tool through registry."""
        if not tool_name:
            return {"success": False, "error": "No tool specified"}

        try:
            result = await self.tool_registry(tool_name, args)
            return result if isinstance(result, dict) else {"success": True, "result": result}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def pause(self) -> None:
        """Pause execution."""
        self._paused = True
        logger.info("Plan execution paused")

    def resume(self) -> None:
        """Resume execution."""
        self._paused = False
        logger.info("Plan execution resumed")

    def cancel(self) -> None:
        """Cancel execution."""
        self._cancel_requested = True
        logger.info("Plan execution cancelled")

    def get_current_plan(self) -> Optional[Plan]:
        """Get currently executing plan."""
        return self._current_plan

    def is_running(self) -> bool:
        return self._running


# High-level async functions for tool integration
async def planner_create_plan(goal: str, template: str = None, params: dict = None) -> dict:
    """Create execution plan from goal or template."""
    from agents.planner import Planner, PlanExecutor
    planner = Planner()
    if template:
        plan = planner.create_plan_from_template(template, params or {})
    else:
        plan = await planner.create_plan_from_goal(goal)
    return {"success": True, "plan_id": plan.id, "goal": plan.goal, "steps": len(plan.steps)}


async def planner_execute_plan(plan_id: str) -> dict:
    """Execute a plan by ID."""
    # Would need plan storage - simplified for now
    return {"success": False, "error": "Plan storage not implemented"}


async def planner_list_templates() -> dict:
    """List available plan templates."""
    from agents.planner import Planner
    planner = Planner()
    return {"success": True, "templates": planner.get_templates()}


async def planner_get_progress(plan_id: str) -> dict:
    """Get plan execution progress."""
    # Would need plan storage
    return {"success": False, "error": "Plan storage not implemented"}