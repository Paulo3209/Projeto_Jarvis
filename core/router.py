import asyncio
from core.plugin_system import get_tool, get_all_tools, ToolSpec
from core.event_bus import (
    EventBus,
    EventType,
    ToolCompletedEvent,
    ToolFailedEvent,
    get_event_bus,
)


class Router:
    """Routes tool calls to registered plugins."""

    def __init__(self):
        self._event_bus: EventBus | None = None
        self._tool_cache: dict[str, ToolSpec] = {}
        self._refresh_tool_cache()

    def _refresh_tool_cache(self) -> None:
        """Refresh tool cache from plugin registry."""
        self._tool_cache = {spec.name: spec for spec in get_all_tools()}

    def get_available_functions(self) -> dict[str, callable]:
        """Get all available functions as a dict (for backward compat)."""
        self._refresh_tool_cache()
        return {name: spec.function for name, spec in self._tool_cache.items()}

    def get_dangerous_tools(self) -> set[str]:
        """Get set of dangerous tool names."""
        self._refresh_tool_cache()
        return {name for name, spec in self._tool_cache.items() if spec.is_dangerous}

    async def _get_event_bus(self) -> EventBus:
        if self._event_bus is None:
            self._event_bus = await get_event_bus()
        return self._event_bus

    def execute(self, function_name: str, arguments: dict | None = None) -> dict:
        """Synchronous execute - emits events via event bus."""
        arguments = arguments or {}

        self._refresh_tool_cache()
        spec = self._tool_cache.get(function_name)

        if not spec:
            return {"success": False, "message": f"Ferramenta desconhecida: {function_name}"}

        fn = spec.function

        # Handle dangerous tools with confirmation
        if spec.is_dangerous:
            confirm_msg = spec.confirmation_message or f"JARVIS vai executar: {function_name}"
            print(f"\n[CONFIRMAÇÃO] {confirm_msg}")
            print(f"Argumentos: {arguments}")
            answer = input("Confirmar? [s/N]: ").strip().lower()
            if answer not in ("s", "sim", "y", "yes"):
                return {"success": False, "message": "Ação cancelada pelo usuário."}

        try:
            result = fn(**arguments)
            self._emit_tool_event(function_name, result, spec)
            return result
        except Exception as e:
            error_result = {"success": False, "message": f"Erro: {type(e).__name__}: {e}"}
            self._emit_tool_event(function_name, error_result, spec)
            return error_result

    async def execute_async(self, function_name: str, arguments: dict | None = None) -> dict:
        """Async execute - emits events via event bus."""
        arguments = arguments or {}

        self._refresh_tool_cache()
        spec = self._tool_cache.get(function_name)

        if not spec:
            return {"success": False, "message": f"Ferramenta desconhecida: {function_name}"}

        fn = spec.function

        # Handle dangerous tools (skip confirmation in async for now)
        if spec.is_dangerous:
            pass  # Could emit event for GUI/Voice to handle confirmation

        try:
            if spec.is_async:
                result = await fn(**arguments)
            else:
                loop = asyncio.get_event_loop()
                result = await loop.run_in_executor(None, lambda: fn(**arguments))

            await self._emit_tool_event_async(function_name, result, spec)
            return result
        except Exception as e:
            error_result = {"success": False, "message": f"Erro: {type(e).__name__}: {e}"}
            await self._emit_tool_event_async(function_name, error_result, spec)
            return error_result

    def _emit_tool_event(self, function_name: str, result: dict, spec: ToolSpec) -> None:
        """Emit tool event (sync, fire-and-forget)."""
        try:
            bus = EventBus._instance
            if bus:
                if result.get("success", False):
                    bus.emit(ToolCompletedEvent(function_name, result, call_id="", source="router"))
                else:
                    bus.emit(ToolFailedEvent(function_name, result.get("message", "Unknown error"), call_id="", source="router"))
        except Exception:
            pass

    async def _emit_tool_event_async(self, function_name: str, result: dict, spec: ToolSpec) -> None:
        """Emit tool event (async)."""
        try:
            bus = await self._get_event_bus()
            if result.get("success", False):
                await bus.emit_async(ToolCompletedEvent(function_name, result, call_id="", source="router"))
            else:
                await bus.emit_async(ToolFailedEvent(function_name, result.get("message", "Unknown error"), call_id="", source="router"))
        except Exception:
            pass