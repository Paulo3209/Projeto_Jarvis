"""
Command Orchestrator - Simultaneous commands, automation rules, batch execution.
Manages complex multi-device, multi-step command sequences.
"""
from __future__ import __future__
import asyncio
import logging
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Set

from core.event_bus import EventBus, EventType, get_event_bus
from agents.executor import WorkflowExecutor, ExecutionMode, ExecutionTask, get_workflow_executor

logger = logging.getLogger(__name__)


class CommandStatus(Enum):
    """Command execution status."""
    PENDING = "pending"
    QUEUED = "queued"
    RUNNING = "running"
    WAITING = "waiting"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    PARTIAL = "partial"


class TriggerType(Enum):
    """Automation trigger types."""
    TIME = "time"                    # Scheduled time
    INTERVAL = "interval"            # Recurring interval
    EVENT = "event"                  # Event bus event
    DEVICE_STATE = "device_state"    # Device status change
    CONDITION = "condition"          # Custom condition
    VOICE = "voice"                  # Voice command
    WEBHOOK = "webhook"              # External webhook
    MANUAL = "manual"                # Manual trigger


@dataclass
class Command:
    """Single command."""
    command_id: str
    target: str  # device_id, "all", "group:name", or tool name
    action: str
    params: Dict = field(default_factory=dict)
    depends_on: List[str] = field(default_factory=list)  # Command IDs
    timeout: float = 30.0
    retry_count: int = 0
    max_retries: int = 2
    metadata: Dict = field(default_factory=dict)


@dataclass
class CommandBatch:
    """Batch of commands to execute."""
    batch_id: str
    name: str
    commands: List[Command]
    mode: ExecutionMode = ExecutionMode.PARALLEL
    continue_on_error: bool = False
    timeout: float = 300.0
    created_at: datetime = field(default_factory=datetime.now)
    status: CommandStatus = CommandStatus.PENDING
    results: Dict[str, Any] = field(default_factory=dict)
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None


@dataclass
class AutomationRule:
    """Automation rule."""
    rule_id: str
    name: str
    description: str
    trigger: TriggerType
    trigger_config: Dict  # Depends on trigger type
    conditions: List[Dict] = field(default_factory=list)  # Additional conditions
    actions: List[Command] = field(default_factory=list)
    enabled: bool = True
    cooldown: float = 0.0  # Minimum time between executions
    last_triggered: Optional[datetime] = None
    trigger_count: int = 0
    metadata: Dict = field(default_factory=dict)


@dataclass
class ScheduledCommand:
    """Scheduled command for future execution."""
    schedule_id: str
    command: Command
    execute_at: datetime
    recurring: bool = False
    interval: Optional[timedelta] = None
    created_at: datetime = field(default_factory=datetime.now)


class CommandOrchestrator:
    """
    Orchestrates complex command sequences across devices and tools.
    Supports batch execution, automation rules, and scheduling.
    """

    def __init__(self):
        self._executor = get_workflow_executor()
        self._event_bus: Optional[EventBus] = None
        self._batches: Dict[str, CommandBatch] = {}
        self._automation_rules: Dict[str, AutomationRule] = {}
        self._scheduled: Dict[str, ScheduledCommand] = {}
        self._running = False
        self._scheduler_task: Optional[asyncio.Task] = None
        self._automation_task: Optional[asyncio.Task] = None
        self._command_queue: asyncio.Queue = asyncio.Queue()
        self._device_groups: Dict[str, List[str]] = {}
        self._command_history: List[Dict] = []
        self._max_history = 1000

    async def initialize(self) -> None:
        """Initialize orchestrator."""
        self._event_bus = await get_event_bus()

        # Subscribe to events for automation triggers
        self._event_bus.subscribe_async(EventType.DEVICE_CONNECTED, self._check_automations)
        self._event_bus.subscribe_async(EventType.DEVICE_DISCONNECTED, self._check_automations)
        self._event_bus.subscribe_async(EventType.TOOL_COMPLETED, self._check_automations)
        self._event_bus.subscribe_async(EventType.STATUS_CHANGE, self._check_automations)

        self._running = True
        self._scheduler_task = asyncio.create_task(self._scheduler_loop())
        self._automation_task = asyncio.create_task(self._automation_loop())

        logger.info("Command Orchestrator initialized")

    def register_device_group(self, group_name: str, device_ids: List[str]) -> None:
        """Register a device group."""
        self._device_groups[group_name] = device_ids

    def get_device_group(self, group_name: str) -> List[str]:
        """Get device IDs in a group."""
        return self._device_groups.get(group_name, [])

    def resolve_target(self, target: str) -> List[str]:
        """Resolve target to list of device IDs or tool names."""
        if target == "all":
            from devices.device_registry import get_device_manager
            manager = get_device_manager()
            return [d.device_id for d in manager.list_devices() if d.connection_status.value == "connected"]

        if target.startswith("group:"):
            group = target[6:]
            return self.get_device_group(group)

        # Single device or tool
        return [target]

    async def execute_batch(self, batch: CommandBatch) -> Dict:
        """Execute a command batch."""
        batch.status = CommandStatus.RUNNING
        batch.started_at = datetime.now()
        self._batches[batch.batch_id] = batch

        try:
            # Build execution tasks
            tasks = []
            for cmd in batch.commands:
                targets = self.resolve_target(cmd.target)
                for target in targets:
                    task = ExecutionTask(
                        task_id=f"{batch.batch_id}_{cmd.command_id}_{target}",
                        tool=cmd.action if not self._is_device_command(cmd.action) else "execute_device_command",
                        args={
                            "device_id": target,
                            "command": cmd.action,
                            "params": cmd.params,
                        } if self._is_device_command(cmd.action) else cmd.params,
                        depends_on=[d for d in cmd.depends_on],
                    )
                    tasks.append(task)

            # Execute via workflow executor
            execution = await self._executor.execute_workflow(
                workflow_id=f"batch_{batch.batch_id}",
                tasks=tasks,
                mode=batch.mode,
            )

            # Collect results
            batch.results = execution.results if hasattr(execution, 'results') else {}
            batch.status = CommandStatus.COMPLETED if execution.status.value == "completed" else CommandStatus.FAILED

        except Exception as e:
            batch.status = CommandStatus.FAILED
            batch.results = {"error": str(e)}
            logger.error(f"Batch execution failed: {e}")

        finally:
            batch.completed_at = datetime.now()
            self._add_to_history(batch)

        return {
            "batch_id": batch.batch_id,
            "status": batch.status.value,
            "results": batch.results,
            "duration": (batch.completed_at - batch.started_at).total_seconds() if batch.started_at and batch.completed_at else 0,
        }

    def _is_device_command(self, action: str) -> bool:
        """Check if action is a device command."""
        device_commands = {
            "shell", "reboot", "shutdown", "screenshot", "install",
            "uninstall", "start_app", "stop_app", "tap", "swipe",
            "input_text", "key_event", "get_battery", "get_info",
            "http_request", "ssh_exec", "mqtt_publish", "hass_call",
        }
        return action in device_commands

    async def execute_simultaneous(
        self,
        commands: List[Command],
        name: str = "simultaneous",
        continue_on_error: bool = True,
    ) -> Dict:
        """Execute commands simultaneously on multiple targets."""
        batch = CommandBatch(
            batch_id=f"sim_{uuid.uuid4().hex[:8]}",
            name=name,
            commands=commands,
            mode=ExecutionMode.PARALLEL,
            continue_on_error=continue_on_error,
        )
        return await self.execute_batch(batch)

    async def execute_sequential(
        self,
        commands: List[Command],
        name: str = "sequential",
    ) -> Dict:
        """Execute commands sequentially."""
        batch = CommandBatch(
            batch_id=f"seq_{uuid.uuid4().hex[:8]}",
            name=name,
            commands=commands,
            mode=ExecutionMode.SEQUENTIAL,
        )
        return await self.execute_batch(batch)

    async def execute_pipeline(
        self,
        commands: List[Command],
        name: str = "pipeline",
    ) -> Dict:
        """Execute commands in pipeline (output of one feeds next)."""
        batch = CommandBatch(
            batch_id=f"pipe_{uuid.uuid4().hex[:8]}",
            name=name,
            commands=commands,
            mode=ExecutionMode.PIPELINE,
        )
        return await self.execute_batch(batch)

    def add_automation_rule(self, rule: AutomationRule) -> None:
        """Add automation rule."""
        self._automation_rules[rule.rule_id] = rule

    def remove_automation_rule(self, rule_id: str) -> bool:
        """Remove automation rule."""
        if rule_id in self._automation_rules:
            del self._automation_rules[rule_id]
            return True
        return False

    def get_automation_rule(self, rule_id: str) -> Optional[AutomationRule]:
        """Get automation rule."""
        return self._automation_rules.get(rule_id)

    def list_automation_rules(self) -> List[AutomationRule]:
        """List all automation rules."""
        return list(self._automation_rules.values())

    def enable_rule(self, rule_id: str) -> bool:
        """Enable automation rule."""
        if rule_id in self._automation_rules:
            self._automation_rules[rule_id].enabled = True
            return True
        return False

    def disable_rule(self, rule_id: str) -> bool:
        """Disable automation rule."""
        if rule_id in self._automation_rules:
            self._automation_rules[rule_id].enabled = False
            return True
        return False

    async def schedule_command(
        self,
        command: Command,
        execute_at: datetime,
        recurring: bool = False,
        interval: timedelta = None,
    ) -> str:
        """Schedule command for future execution."""
        schedule_id = f"sched_{uuid.uuid4().hex[:8]}"
        scheduled = ScheduledCommand(
            schedule_id=schedule_id,
            command=command,
            execute_at=execute_at,
            recurring=recurring,
            interval=interval,
        )
        self._scheduled[schedule_id] = scheduled
        return schedule_id

    def cancel_scheduled(self, schedule_id: str) -> bool:
        """Cancel scheduled command."""
        if schedule_id in self._scheduled:
            del self._scheduled[schedule_id]
            return True
        return False

    def get_scheduled(self) -> List[ScheduledCommand]:
        """Get all scheduled commands."""
        return list(self._scheduled.values())

    async def _scheduler_loop(self) -> None:
        """Check and execute scheduled commands."""
        while self._running:
            try:
                now = datetime.now()
                to_execute = []

                for schedule_id, scheduled in list(self._scheduled.items()):
                    if scheduled.execute_at <= now:
                        to_execute.append((schedule_id, scheduled))

                for schedule_id, scheduled in to_execute:
                    await self._execute_scheduled(schedule_id, scheduled)

            except Exception as e:
                logger.error(f"Scheduler error: {e}")

            await asyncio.sleep(1.0)

    async def _execute_scheduled(self, schedule_id: str, scheduled: ScheduledCommand) -> None:
        """Execute a scheduled command."""
        targets = self.resolve_target(scheduled.command.target)
        for target in targets:
            task = ExecutionTask(
                task_id=f"{schedule_id}_{target}",
                tool="execute_device_command" if self._is_device_command(scheduled.command.action) else scheduled.command.action,
                args={
                    "device_id": target,
                    "command": scheduled.command.action,
                    "params": scheduled.command.params,
                } if self._is_device_command(scheduled.command.action) else scheduled.command.params,
            )
            await self._executor.execute_task(task)

        if scheduled.recurring and scheduled.interval:
            scheduled.execute_at += scheduled.interval
        else:
            del self._scheduled[schedule_id]

    async def _automation_loop(self) -> None:
        """Check automation rules periodically."""
        while self._running:
            try:
                await self._check_automations()
            except Exception as e:
                logger.error(f"Automation loop error: {e}")
            await asyncio.sleep(5.0)

    async def _check_automations(self, event=None) -> None:
        """Check and trigger automation rules."""
        event_type = event.data.get("event_type") if event else None
        event_data = event.data if event else {}

        for rule in self._automation_rules.values():
            if not rule.enabled:
                continue

            # Check cooldown
            if rule.cooldown > 0 and rule.last_triggered:
                if (datetime.now() - rule.last_triggered).total_seconds() < rule.cooldown:
                    continue

            # Check trigger
            triggered = await self._evaluate_trigger(rule, event_type, event_data)

            if triggered:
                # Check conditions
                if await self._evaluate_conditions(rule, event_data):
                    await self._execute_rule_actions(rule)
                    rule.last_triggered = datetime.now()
                    rule.trigger_count += 1

    async def _evaluate_trigger(self, rule: AutomationRule, event_type: str, event_data: Dict) -> bool:
        """Evaluate if trigger condition is met."""
        trigger = rule.trigger

        if trigger == TriggerType.EVENT:
            return event_type == rule.trigger_config.get("event_type")

        elif trigger == TriggerType.DEVICE_STATE:
            device_id = rule.trigger_config.get("device_id")
            expected_status = rule.trigger_config.get("status")
            return (
                event_type == "device_status_changed" and
                event_data.get("device_id") == device_id and
                event_data.get("status") == expected_status
            )

        elif trigger == TriggerType.TIME:
            # Check if current time matches
            schedule = rule.trigger_config.get("schedule")  # cron-like
            # Simplified - would use croniter in real implementation
            return False

        elif trigger == TriggerType.INTERVAL:
            interval = rule.trigger_config.get("seconds", 0)
            # Would track last execution
            return False

        elif trigger == TriggerType.VOICE:
            phrase = rule.trigger_config.get("phrase", "").lower()
            return phrase in event_data.get("text", "").lower()

        elif trigger == TriggerType.CONDITION:
            # Custom condition function
            condition_fn = rule.trigger_config.get("condition")
            if callable(condition_fn):
                return condition_fn(event_data)
            return False

        return False

    async def _evaluate_conditions(self, rule: AutomationRule, event_data: Dict) -> bool:
        """Evaluate additional conditions."""
        for condition in rule.conditions:
            cond_type = condition.get("type")
            if cond_type == "device_online":
                device_id = condition.get("device_id")
                from devices.device_registry import get_device_manager
                manager = get_device_manager()
                device = manager.get_device(device_id)
                if not device or device.connection_status.value != "connected":
                    return False
            elif cond_type == "time_between":
                start = condition.get("start")  # "HH:MM"
                end = condition.get("end")
                now = datetime.now().time()
                if not (start <= now.strftime("%H:%M") <= end):
                    return False
            elif cond_type == "custom":
                fn = condition.get("function")
                if callable(fn) and not fn(event_data):
                    return False
        return True

    async def _execute_rule_actions(self, rule: AutomationRule) -> None:
        """Execute automation rule actions."""
        commands = []
        for action in rule.actions:
            commands.append(Command(
                command_id=f"{rule.rule_id}_{action.action}_{uuid.uuid4().hex[:4]}",
                target=action.target,
                action=action.action,
                params=action.params,
            ))

        if commands:
            await self.execute_simultaneous(commands, name=f"automation_{rule.rule_id}")

    def _add_to_history(self, batch: CommandBatch) -> None:
        """Add batch to history."""
        self._command_history.append({
            "batch_id": batch.batch_id,
            "name": batch.name,
            "status": batch.status.value,
            "command_count": len(batch.commands),
            "started_at": batch.started_at.isoformat() if batch.started_at else None,
            "completed_at": batch.completed_at.isoformat() if batch.completed_at else None,
        })
        if len(self._command_history) > self._max_history:
            self._command_history = self._command_history[-self._max_history:]

    def get_batch_status(self, batch_id: str) -> Optional[Dict]:
        """Get batch execution status."""
        batch = self._batches.get(batch_id)
        if not batch:
            return None
        return {
            "batch_id": batch.batch_id,
            "name": batch.name,
            "status": batch.status.value,
            "results": batch.results,
            "started_at": batch.started_at.isoformat() if batch.started_at else None,
            "completed_at": batch.completed_at.isoformat() if batch.completed_at else None,
        }

    def get_history(self, limit: int = 50) -> List[Dict]:
        """Get command history."""
        return self._command_history[-limit:]

    async def shutdown(self) -> None:
        """Shutdown orchestrator."""
        self._running = False
        if self._scheduler_task:
            self._scheduler_task.cancel()
        if self._automation_task:
            self._automation_task.cancel()
        logger.info("Command Orchestrator shutdown")


# Global instance
_command_orchestrator: Optional[CommandOrchestrator] = None


def get_command_orchestrator() -> CommandOrchestrator:
    """Get global command orchestrator."""
    global _command_orchestrator
    if _command_orchestrator is None:
        _command_orchestrator = CommandOrchestrator()
    return _command_orchestrator