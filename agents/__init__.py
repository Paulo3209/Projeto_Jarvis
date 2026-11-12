"""
Agents Module - Autonomous agent capabilities for JARVIS.
Includes planning, execution, and permission management.
"""
from .planner import (
    Planner,
    PlanExecutor,
    Plan,
    PlanStep,
    StepStatus,
    StepType,
    planner_create_plan,
    planner_execute_plan,
    planner_list_templates,
    planner_get_progress,
)

from .executor import (
    TaskExecutor,
    WorkflowExecutor,
    WorkflowBuilder,
    Workflow,
    ExecutionTask,
    ExecutionResult,
    WorkflowExecution,
    ExecutionStatus,
    ExecutionMode,
    executor_create_workflow,
    executor_run_workflow,
    executor_run_adhoc,
)

from .permissions import (
    PermissionManager,
    PermissionRule,
    ApprovalRequest,
    AuditEntry,
    PermissionLevel,
    RiskLevel,
    get_permission_manager,
    permissions_check,
    permissions_respond,
    permissions_pending,
    permissions_audit,
    permissions_rules,
    permissions_add_rule,
)

__all__ = [
    # Planner
    "Planner",
    "PlanExecutor",
    "Plan",
    "PlanStep",
    "StepStatus",
    "StepType",
    "planner_create_plan",
    "planner_execute_plan",
    "planner_list_templates",
    "planner_get_progress",

    # Executor
    "TaskExecutor",
    "WorkflowExecutor",
    "WorkflowBuilder",
    "Workflow",
    "ExecutionTask",
    "ExecutionResult",
    "WorkflowExecution",
    "ExecutionStatus",
    "ExecutionMode",
    "executor_create_workflow",
    "executor_run_workflow",
    "executor_run_adhoc",

    # Permissions
    "PermissionManager",
    "PermissionRule",
    "ApprovalRequest",
    "AuditEntry",
    "PermissionLevel",
    "RiskLevel",
    "get_permission_manager",
    "permissions_check",
    "permissions_respond",
    "permissions_pending",
    "permissions_audit",
    "permissions_rules",
    "permissions_add_rule",
]