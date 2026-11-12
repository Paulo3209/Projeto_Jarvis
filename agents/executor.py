"""
Executor Agent - Task execution engine for JARVIS.
Handles tool execution, workflow management, and result aggregation.
"""
from __future__ import annotations
import asyncio
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Union
from pathlib import Path

logger = logging.getLogger(__name__)


class ExecutionStatus(Enum):
    """Execution status."""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    PARTIAL = "partial"  # Some steps succeeded, some failed


class ExecutionMode(Enum):
    """Execution mode."""
    SEQUENTIAL = "sequential"
    PARALLEL = "parallel"
    PIPELINE = "pipeline"  # Output of one feeds into next


@dataclass
class ExecutionTask:
    """A task to execute."""
    id: str
    name: str
    tool_name: str
    args: Dict = field(default_factory=dict)
    depends_on: List[str] = field(default_factory=list)
    condition: Optional[str] = None  # Python expression to evaluate
    timeout: float = 60.0
    retries: int = 0
    max_retries: int = 3
    continue_on_failure: bool = False


@dataclass
class ExecutionResult:
    """Result of a task execution."""
    task_id: str
    success: bool
    result: Any = None
    error: Optional[str] = None
    duration: float = 0.0
    retries: int = 0
    timestamp: datetime = field(default_factory=datetime.now)


@dataclass
class Workflow:
    """A workflow definition."""
    id: str
    name: str
    description: str = ""
    tasks: List[ExecutionTask] = field(default_factory=list)
    mode: ExecutionMode = ExecutionMode.SEQUENTIAL
    metadata: Dict = field(default_factory=dict)
    created_at: datetime = field(default_factory=datetime.now)


@dataclass
class WorkflowExecution:
    """A workflow execution instance."""
    workflow_id: str
    execution_id: str
    status: ExecutionStatus = ExecutionStatus.PENDING
    results: Dict[str, ExecutionResult] = field(default_factory=dict)
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    current_task: Optional[str] = None
    variables: Dict = field(default_factory=dict)  # Runtime variables

    def get_result(self, task_id: str) -> Optional[ExecutionResult]:
        return self.results.get(task_id)

    def is_task_ready(self, task: ExecutionTask) -> bool:
        """Check if task dependencies are satisfied."""
        for dep_id in task.depends_on:
            result = self.results.get(dep_id)
            if not result or not result.success:
                return False
        return True

    def evaluate_condition(self, condition: str) -> bool:
        """Evaluate a condition expression."""
        if not condition:
            return True
        try:
            # Safe evaluation with limited scope
            return bool(eval(condition, {"__builtins__": {}}, self.variables))
        except Exception as e:
            logger.warning(f"Condition evaluation failed: {condition} - {e}")
            return False


class TaskExecutor:
    """
    Executes individual tasks with retries, timeouts, and error handling.
    """

    def __init__(
        self,
        tool_registry: Callable[[str, Dict], Any],
        default_timeout: float = 60.0,
        max_concurrent: int = 5
    ):
        self.tool_registry = tool_registry
        self.default_timeout = default_timeout
        self.max_concurrent = max_concurrent
        self._semaphore: Optional[asyncio.Semaphore] = None

    async def execute_task(
        self,
        task: ExecutionTask,
        execution: WorkflowExecution
    ) -> ExecutionResult:
        """Execute a single task."""
        start_time = asyncio.get_event_loop().time()
        task_id = task.id

        # Evaluate condition
        if task.condition and not execution.evaluate_condition(task.condition):
            return ExecutionResult(
                task_id=task_id,
                success=True,
                result={"skipped": True, "reason": "Condition not met"},
                duration=0
            )

        # Prepare arguments with variable substitution
        args = self._substitute_variables(task.args, execution.variables)

        last_error = None
        for attempt in range(task.max_retries + 1):
            try:
                logger.debug(f"Executing task {task_id} (attempt {attempt + 1})")

                # Execute with timeout
                result = await asyncio.wait_for(
                    self._call_tool(task.tool_name, args),
                    timeout=task.timeout
                )

                duration = asyncio.get_event_loop().time() - start_time

                if isinstance(result, dict) and result.get("success", False):
                    # Store result in variables for next tasks
                    execution.variables[f"task_{task_id}_result"] = result
                    return ExecutionResult(
                        task_id=task_id,
                        success=True,
                        result=result,
                        duration=duration,
                        retries=attempt
                    )
                else:
                    last_error = result.get("error", "Unknown error") if isinstance(result, dict) else str(result)

            except asyncio.TimeoutError:
                last_error = f"Task timed out after {task.timeout}s"
            except Exception as e:
                last_error = f"Execution error: {e}"
                logger.error(f"Task {task_id} error: {e}")

            # Retry delay
            if attempt < task.max_retries:
                await asyncio.sleep(1.0 * (attempt + 1))

        duration = asyncio.get_event_loop().time() - start_time
        return ExecutionResult(
            task_id=task_id,
            success=False,
            error=last_error,
            duration=duration,
            retries=task.max_retries
        )

    def _substitute_variables(self, args: Dict, variables: Dict) -> Dict:
        """Substitute ${var} patterns in args."""
        import re

        def substitute_value(value: Any) -> Any:
            if isinstance(value, str):
                def repl(match):
                    var_name = match.group(1)
                    return str(variables.get(var_name, match.group(0)))
                return re.sub(r'\$\{([^}]+)\}', repl, value)
            elif isinstance(value, dict):
                return {k: substitute_value(v) for k, v in value.items()}
            elif isinstance(value, list):
                return [substitute_value(v) for v in value]
            return value

        return substitute_value(args)

    async def _call_tool(self, tool_name: str, args: Dict) -> Any:
        """Call tool through registry."""
        try:
            result = await self.tool_registry(tool_name, args)
            return result if isinstance(result, dict) else {"success": True, "result": result}
        except Exception as e:
            return {"success": False, "error": str(e)}


class WorkflowExecutor:
    """
    Executes workflows with different execution modes.
    """

    def __init__(self, task_executor: TaskExecutor):
        self.task_executor = task_executor
        self._running_executions: Dict[str, WorkflowExecution] = {}
        self._progress_callbacks: List[Callable[[WorkflowExecution, ExecutionTask, ExecutionResult], None]] = []

    def add_progress_callback(self, callback: Callable) -> None:
        self._progress_callbacks.append(callback)

    async def execute_workflow(
        self,
        workflow: Workflow,
        initial_variables: Dict = None
    ) -> WorkflowExecution:
        """Execute a workflow."""
        execution = WorkflowExecution(
            workflow_id=workflow.id,
            execution_id=str(uuid.uuid4())[:8],
            variables=initial_variables or {}
        )

        self._running_executions[execution.execution_id] = execution
        execution.status = ExecutionStatus.RUNNING
        execution.started_at = datetime.now()

        logger.info(f"Starting workflow: {workflow.name} ({execution.execution_id})")

        try:
            if workflow.mode == ExecutionMode.SEQUENTIAL:
                await self._execute_sequential(workflow, execution)
            elif workflow.mode == ExecutionMode.PARALLEL:
                await self._execute_parallel(workflow, execution)
            elif workflow.mode == ExecutionMode.PIPELINE:
                await self._execute_pipeline(workflow, execution)

            # Determine final status
            failed_tasks = [r for r in execution.results.values() if not r.success]
            if failed_tasks:
                if len(failed_tasks) == len(workflow.tasks):
                    execution.status = ExecutionStatus.FAILED
                else:
                    execution.status = ExecutionStatus.PARTIAL
            else:
                execution.status = ExecutionStatus.COMPLETED

        except Exception as e:
            execution.status = ExecutionStatus.FAILED
            logger.error(f"Workflow execution failed: {e}")

        execution.completed_at = datetime.now()
        del self._running_executions[execution.execution_id]

        logger.info(f"Workflow {workflow.name} completed with status: {execution.status.value}")
        return execution

    async def _execute_sequential(
        self,
        workflow: Workflow,
        execution: WorkflowExecution
    ) -> None:
        """Execute tasks sequentially."""
        for task in workflow.tasks:
            execution.current_task = task.id

            # Check if ready (for sequential, always ready if dependencies met)
            if not execution.is_task_ready(task):
                # Dependencies failed
                if not task.continue_on_failure:
                    execution.status = ExecutionStatus.FAILED
                    return

            result = await self.task_executor.execute_task(task, execution)
            execution.results[task.id] = result

            # Notify progress
            for callback in self._progress_callbacks:
                try:
                    callback(execution, task, result)
                except Exception as e:
                    logger.error(f"Progress callback error: {e}")

            if not result.success and not task.continue_on_failure:
                break

    async def _execute_parallel(
        self,
        workflow: Workflow,
        execution: WorkflowExecution
    ) -> None:
        """Execute tasks in parallel (respecting dependencies)."""
        completed = set()
        pending = {task.id: task for task in workflow.tasks}

        while pending:
            # Find ready tasks
            ready = []
            for task_id, task in list(pending.items()):
                if execution.is_task_ready(task):
                    ready.append(task)

            if not ready:
                # Check for circular dependency or failed deps
                remaining = list(pending.values())
                if any(not t.continue_on_failure for t in remaining):
                    execution.status = ExecutionStatus.FAILED
                    break
                # All remaining have continue_on_failure, execute anyway
                ready = remaining

            # Execute ready tasks in parallel
            tasks = [self.task_executor.execute_task(task, execution) for task in ready]
            results = await asyncio.gather(*tasks, return_exceptions=True)

            for task, result in zip(ready, results):
                if isinstance(result, Exception):
                    result = ExecutionResult(
                        task_id=task.id,
                        success=False,
                        error=str(result)
                    )

                execution.results[task.id] = result
                completed.add(task.id)
                del pending[task.id]

                for callback in self._progress_callbacks:
                    try:
                        callback(execution, task, result)
                    except Exception as e:
                        logger.error(f"Progress callback error: {e}")

    async def _execute_pipeline(
        self,
        workflow: Workflow,
        execution: WorkflowExecution
    ) -> None:
        """Execute tasks in pipeline (output feeds into next)."""
        for i, task in enumerate(workflow.tasks):
            execution.current_task = task.id

            # For pipeline, inject previous task's result
            if i > 0:
                prev_task = workflow.tasks[i - 1]
                prev_result = execution.results.get(prev_task.id)
                if prev_result and prev_result.success:
                    execution.variables["pipeline_input"] = prev_result.result

            result = await self.task_executor.execute_task(task, execution)
            execution.results[task.id] = result

            for callback in self._progress_callbacks:
                try:
                    callback(execution, task, result)
                except Exception as e:
                    logger.error(f"Progress callback error: {e}")

            if not result.success and not task.continue_on_failure:
                break

    def get_execution(self, execution_id: str) -> Optional[WorkflowExecution]:
        """Get running execution by ID."""
        return self._running_executions.get(execution_id)

    def cancel_execution(self, execution_id: str) -> bool:
        """Cancel a running execution."""
        execution = self._running_executions.get(execution_id)
        if execution:
            execution.status = ExecutionStatus.CANCELLED
            return True
        return False


# Workflow builder for fluent API
class WorkflowBuilder:
    """Fluent builder for creating workflows."""

    def __init__(self, name: str, description: str = ""):
        self.workflow = Workflow(
            id=str(uuid.uuid4())[:8],
            name=name,
            description=description
        )

    def add_task(
        self,
        name: str,
        tool_name: str,
        args: Dict = None,
        depends_on: List[str] = None,
        condition: str = None,
        timeout: float = 60.0,
        retries: int = 3,
        continue_on_failure: bool = False
    ) -> "WorkflowBuilder":
        task = ExecutionTask(
            id=str(uuid.uuid4())[:8],
            name=name,
            tool_name=tool_name,
            args=args or {},
            depends_on=depends_on or [],
            condition=condition,
            timeout=timeout,
            max_retries=retries,
            continue_on_failure=continue_on_failure
        )
        self.workflow.tasks.append(task)
        return self

    def set_mode(self, mode: ExecutionMode) -> "WorkflowBuilder":
        self.workflow.mode = mode
        return self

    def build(self) -> Workflow:
        return self.workflow


# High-level async functions for tool integration
async def executor_create_workflow(
    name: str,
    description: str = "",
    tasks: List[Dict] = None,
    mode: str = "sequential"
) -> dict:
    """Create a workflow definition."""
    from agents.executor import WorkflowBuilder, ExecutionMode

    builder = WorkflowBuilder(name, description)

    if tasks:
        for task in tasks:
            builder.add_task(
                name=task.get("name", "Task"),
                tool_name=task.get("tool"),
                args=task.get("args", {}),
                depends_on=task.get("depends_on"),
                condition=task.get("condition"),
                timeout=task.get("timeout", 60.0),
                retries=task.get("retries", 3),
                continue_on_failure=task.get("continue_on_failure", False)
            )

    if mode:
        builder.set_mode(ExecutionMode(mode))

    workflow = builder.build()
    return {
        "success": True,
        "workflow_id": workflow.id,
        "name": workflow.name,
        "tasks": len(workflow.tasks)
    }


async def executor_run_workflow(workflow_id: str, variables: dict = None) -> dict:
    """Run a workflow by ID."""
    # Would need workflow storage
    return {"success": False, "error": "Workflow storage not implemented"}


async def executor_run_adhoc(
    tasks: List[Dict],
    mode: str = "sequential",
    variables: dict = None
) -> dict:
    """Run ad-hoc tasks without saving workflow."""
    from agents.executor import WorkflowBuilder, ExecutionMode, WorkflowExecutor, TaskExecutor
    from core.plugin_system import get_tool

    async def tool_registry(tool_name: str, args: Dict):
        tool = get_tool(tool_name)
        if tool and tool.function:
            if tool.is_async:
                return await tool.function(**args)
            else:
                return tool.function(**args)
        return {"success": False, "error": f"Tool not found: {tool_name}"}

    builder = WorkflowBuilder("adhoc", "Ad-hoc execution")
    for task in tasks:
        builder.add_task(
            name=task.get("name", "Task"),
            tool_name=task.get("tool"),
            args=task.get("args", {}),
            depends_on=task.get("depends_on"),
            condition=task.get("condition"),
            timeout=task.get("timeout", 60.0),
            retries=task.get("retries", 3)
        )
    builder.set_mode(ExecutionMode(mode))

    workflow = builder.build()
    task_executor = TaskExecutor(tool_registry)
    workflow_executor = WorkflowExecutor(task_executor)

    execution = await workflow_executor.execute_workflow(workflow, variables or {})

    return {
        "success": execution.status in (ExecutionStatus.COMPLETED, ExecutionStatus.PARTIAL),
        "execution_id": execution.execution_id,
        "status": execution.status.value,
        "results": {
            task_id: {
                "success": r.success,
                "result": r.result,
                "error": r.error,
                "duration": r.duration
            }
            for task_id, r in execution.results.items()
        }
    }

async def _plugin_tool_registry(tool_name: str, args: Dict):
    """Executa uma ferramenta registrada no plugin_system."""
    from core.plugin_system import get_tool
    tool = get_tool(tool_name)
    if tool and tool.function:
        if tool.is_async:
            return await tool.function(**args)
        return tool.function(**args)
    return {"success": False, "error": f"Tool not found: {tool_name}"}


_workflow_executor: Optional[WorkflowExecutor] = None


def get_workflow_executor() -> WorkflowExecutor:
    """Instância compartilhada do WorkflowExecutor (usada pelo command_center)."""
    global _workflow_executor
    if _workflow_executor is None:
        _workflow_executor = WorkflowExecutor(TaskExecutor(_plugin_tool_registry))
    return _workflow_executor
