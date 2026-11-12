"""
Agents Tools - Planning, execution, and permissions tools for JARVIS.
Registers agent-related functions as tools.
"""
from core.plugin_system import tool, ToolCategory


# ===== Planner Tools =====

@tool(
    description="Cria um plano de execução a partir de um objetivo ou template.",
    category=ToolCategory.SYSTEM,
)
async def planner_create_plan(goal: str = None, template: str = None, params: dict = None) -> dict:
    """Cria plano de execução.

    Args:
        goal: Objetivo em linguagem natural (ex: "preparar ambiente de trabalho")
        template: Nome do template pré-definido (ex: "prepare_work_environment")
        params: Parâmetros para o template
    """
    from agents.planner import planner_create_plan as _planner_create_plan
    return await _planner_create_plan(goal, template, params)


@tool(
    description="Lista templates de plano disponíveis.",
    category=ToolCategory.SYSTEM,
)
async def planner_list_templates() -> dict:
    """Lista templates de plano disponíveis."""
    from agents.planner import planner_list_templates as _planner_list_templates
    return await _planner_list_templates()


# ===== Executor Tools =====

@tool(
    description="Executa tarefas ad-hoc (sequencial, paralelo ou pipeline).",
    category=ToolCategory.SYSTEM,
)
async def executor_run_adhoc(tasks: list, mode: str = "sequential", variables: dict = None) -> dict:
    """Executa tarefas sem criar workflow persistente.

    Args:
        tasks: Lista de tarefas [{name, tool, args, depends_on?, condition?, timeout?, retries?}]
        mode: Modo de execução (sequential, parallel, pipeline)
        variables: Variáveis iniciais
    """
    from agents.executor import executor_run_adhoc as _executor_run_adhoc
    return await _executor_run_adhoc(tasks, mode, variables)


@tool(
    description="Cria definição de workflow reutilizável.",
    category=ToolCategory.SYSTEM,
)
async def executor_create_workflow(name: str, description: str = "", tasks: list = None, mode: str = "sequential") -> dict:
    """Cria workflow reutilizável.

    Args:
        name: Nome do workflow
        description: Descrição
        tasks: Lista de tarefas
        mode: Modo (sequential, parallel, pipeline)
    """
    from agents.executor import executor_create_workflow as _executor_create_workflow
    return await _executor_create_workflow(name, description, tasks, mode)


# ===== Permissions Tools =====

@tool(
    description="Verifica se uma execução de ferramenta é permitida.",
    category=ToolCategory.SYSTEM,
)
async def permissions_check(tool_name: str, args: dict, user: str = "local", context: str = "") -> dict:
    """Verifica permissão para executar ferramenta.

    Args:
        tool_name: Nome da ferramenta
        args: Argumentos
        user: Usuário
        context: Contexto da execução
    """
    from agents.permissions import permissions_check as _permissions_check
    return await _permissions_check(tool_name, args, user, context)


@tool(
    description="Responde a uma solicitação de aprovação pendente.",
    category=ToolCategory.SYSTEM,
)
async def permissions_respond(approval_id: str, decision: str) -> dict:
    """Responde a aprovação pendente.

    Args:
        approval_id: ID da aprovação
        decision: Decisão (deny, allow_once, allow_session, allow_always)
    """
    from agents.permissions import permissions_respond as _permissions_respond
    return await _permissions_respond(approval_id, decision)


@tool(
    description="Lista solicitações de aprovação pendentes.",
    category=ToolCategory.SYSTEM,
)
async def permissions_pending() -> dict:
    """Lista aprovações pendentes."""
    from agents.permissions import permissions_pending as _permissions_pending
    return await _permissions_pending()


@tool(
    description="Consulta log de auditoria de execuções.",
    category=ToolCategory.SYSTEM,
)
async def permissions_audit(limit: int = 100, tool_name: str = None, risk_level: str = None, hours: int = 24) -> dict:
    """Consulta log de auditoria.

    Args:
        limit: Máximo de entradas
        tool_name: Filtrar por ferramenta
        risk_level: Filtrar por risco (low, medium, high, critical)
        hours: Últimas N horas
    """
    from agents.permissions import permissions_audit as _permissions_audit
    return await _permissions_audit(limit, tool_name, risk_level, hours)


@tool(
    description="Lista regras de permissão configuradas.",
    category=ToolCategory.SYSTEM,
)
async def permissions_rules() -> dict:
    """Lista regras de permissão."""
    from agents.permissions import permissions_rules as _permissions_rules
    return await _permissions_rules()


@tool(
    description="Adiciona regra de permissão personalizada.",
    category=ToolCategory.SYSTEM,
)
async def permissions_add_rule(
    tool_pattern: str,
    risk_level: str,
    requires_approval: bool = True,
    description: str = ""
) -> dict:
    """Adiciona regra de permissão.

    Args:
        tool_pattern: Padrão glob (ex: "meu_tool_*")
        risk_level: Nível de risco (low, medium, high, critical)
        requires_approval: Se requer aprovação
        description: Descrição da regra
    """
    from agents.permissions import permissions_add_rule as _permissions_add_rule
    return await _permissions_add_rule(tool_pattern, risk_level, requires_approval, description)