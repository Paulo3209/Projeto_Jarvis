"""
Brain (Gemini Interactions API) com persona J.A.R.V.I.S. e loop de ferramentas.

- Envia a personalidade via `system_instruction` (antes era montada mas nunca enviada).
- Executa chamadas de função em loop: modelo pede tool -> executamos -> devolvemos
  o resultado -> modelo continua, até responder em texto (máx. MAX_TOOL_ROUNDS).
- `tool_names` permite restringir o conjunto de ferramentas (ex.: modo voz),
  já que enviar as ~190 ferramentas de uma vez confunde o modelo.
"""
import json
import asyncio
from typing import AsyncGenerator, Iterable, Optional

from google import genai
from google.genai._gaos.types.interactions import (
    StepDelta,
    StepStart,
    StepStop,
    FunctionCallStep,
    InteractionCompletedEvent,
)
from config.settings import GEMINI_API_KEY, MODEL, SYSTEM_PROMPT
from core.router import Router
from core.event_bus import (
    EventBus,
    UserMessageEvent,
    AssistantTokenEvent,
    AssistantResponseCompleteEvent,
    ToolCalledEvent,
    ToolCompletedEvent,
    ToolFailedEvent,
    get_event_bus,
)
from core.personality import Personality, PersonalityProcessor, DEFAULT_PERSONALITY
from core.plugin_system import get_gemini_functions, auto_discover_tools, get_tool

MAX_TOOL_ROUNDS = 6


class Brain:
    def __init__(self, personality: Personality = DEFAULT_PERSONALITY, model: Optional[str] = None):
        if not GEMINI_API_KEY:
            raise RuntimeError("GEMINI_API_KEY não encontrada no .env")

        self.client = genai.Client(api_key=GEMINI_API_KEY)
        self.model = model or MODEL
        self.router = Router()
        self.previous_interaction_id = None
        self._event_bus: EventBus | None = None
        self._response_buffer: list[str] = []

        # Personality system
        self.personality = personality
        self.personality_processor = PersonalityProcessor(personality)
        self.system_prompt = self._build_system_prompt()

        # Auto-discover tools from plugins
        auto_discover_tools()
        self.tools = get_gemini_functions()
        self._dangerous = self.router.get_dangerous_tools()

    def _build_system_prompt(self, spoken: bool = False) -> str:
        """Persona + regras técnicas de ferramentas."""
        personality_prompt = self.personality.get_system_prompt_injection(spoken=spoken)
        return f"{personality_prompt}\n\n{SYSTEM_PROMPT.strip()}"

    def _select_tools(self, use_tools: bool, tool_names: Optional[Iterable[str]]) -> list:
        if not use_tools:
            return []
        if tool_names is None:
            selected = list(self.tools)
        else:
            wanted = set(tool_names)
            selected = [t for t in self.tools if t.get("name") in wanted]
        selected.append({"type": "google_search"})
        return selected

    async def _get_event_bus(self) -> EventBus:
        if self._event_bus is None:
            self._event_bus = await get_event_bus()
        return self._event_bus

    def reset(self) -> None:
        """Esquece o contexto da conversa."""
        self.previous_interaction_id = None

    async def think(
        self,
        user_message: str,
        use_tools: bool = False,
        tool_names: Optional[Iterable[str]] = None,
        spoken: bool = False,
        allow_dangerous: bool = True,
        tool_executor=None,
    ) -> AsyncGenerator[str, None]:
        """Gera a resposta em streaming, executando ferramentas quando necessário.

        Args:
            user_message: mensagem do usuário
            use_tools: habilita function calling
            tool_names: restringe a estas ferramentas (None = todas)
            spoken: resposta será falada (curta, sem Markdown)
            allow_dangerous: se False, ferramentas perigosas são recusadas
                (útil no modo voz, onde não há terminal para confirmar)
            tool_executor: async (name, args) -> dict. Substitui a execução padrão
                (o JarvisAgent usa para confirmar ações sensíveis por voz)
        """
        bus = await self._get_event_bus()
        bus.emit(UserMessageEvent(user_message, source="brain"))

        self._response_buffer = []
        tools = self._select_tools(use_tools, tool_names)
        system_prompt = self._build_system_prompt(spoken=spoken)
        next_input: object = user_message

        for _round in range(MAX_TOOL_ROUNDS + 1):
            calls: dict[int, dict] = {}

            kwargs = {
                "model": self.model,
                "input": next_input,
                "system_instruction": system_prompt,
                "tools": tools,
                "stream": True,
            }
            if self.previous_interaction_id:
                kwargs["previous_interaction_id"] = self.previous_interaction_id

            streaming_client = self.client.aio.interactions.with_streaming_response
            async with streaming_client.create(**kwargs) as stream:
                async_stream = await stream.parse()
                async for event in async_stream:
                    if isinstance(event, InteractionCompletedEvent):
                        if event.interaction.id:
                            self.previous_interaction_id = event.interaction.id
                        break

                    if isinstance(event, StepStart) and isinstance(event.step, FunctionCallStep):
                        calls[event.index] = {
                            "id": event.step.id,
                            "name": event.step.name,
                            "arguments": dict(event.step.arguments or {}),
                            "partial": "",
                        }
                        continue

                    if isinstance(event, StepDelta):
                        delta = event.delta
                        dtype = getattr(delta, "type", None)
                        if dtype == "text" and getattr(delta, "text", None):
                            token = delta.text
                            self._response_buffer.append(token)
                            bus.emit(AssistantTokenEvent(token, source="brain"))
                            yield token
                        elif dtype == "arguments_delta" and event.index in calls:
                            calls[event.index]["partial"] += getattr(delta, "arguments", "") or ""
                        continue

                    if isinstance(event, StepStop) and event.index in calls:
                        call = calls[event.index]
                        if call["partial"]:
                            try:
                                call["arguments"] = json.loads(call["partial"])
                            except json.JSONDecodeError:
                                pass

            if not calls:
                break  # Resposta final em texto

            # Executa as ferramentas pedidas e devolve os resultados ao modelo
            results = []
            for call in calls.values():
                result = await self._run_tool(call, bus, allow_dangerous, tool_executor)
                results.append({
                    "type": "function_result",
                    "name": call["name"],
                    "call_id": call["id"],
                    "result": [{"type": "text", "text": json.dumps(result, ensure_ascii=False, default=str)}],
                })
            next_input = results

        full_response = "".join(self._response_buffer)
        processed_response = self.personality_processor.process(full_response, "general")
        bus.emit(AssistantResponseCompleteEvent(processed_response, source="brain"))

    async def _run_tool(self, call: dict, bus: EventBus, allow_dangerous: bool, tool_executor=None) -> dict:
        name, args = call["name"], call["arguments"] or {}
        bus.emit(ToolCalledEvent(name, args, call["id"], source="brain"))

        if tool_executor is not None:
            result = await tool_executor(name, args)
        elif not allow_dangerous and name in self._dangerous:
            result = {
                "success": False,
                "message": "Ação sensível bloqueada no modo voz. Peça ao usuário para confirmar pelo terminal/HUD.",
            }
        else:
            spec = self.router._tool_cache.get(name) or get_tool(name)
            if spec is not None and spec.is_async and not spec.is_dangerous:
                # Router.execute (sync) não faz await de ferramentas async
                result = await self.router.execute_async(name, args)
            else:
                result = await asyncio.get_running_loop().run_in_executor(
                    None, self.router.execute, name, args
                )
            if not isinstance(result, dict):
                result = {"success": True, "result": result}

        if result.get("success", False):
            bus.emit(ToolCompletedEvent(name, result, call["id"], source="brain"))
        else:
            bus.emit(ToolFailedEvent(name, result.get("message", "Erro desconhecido"), call["id"], source="brain"))
        return result

    # Keep synchronous version for backward compatibility
    def think_sync(self, user_message: str) -> str:
        """Synchronous version - collects all streamed tokens and returns complete response."""
        async def collect():
            result = []
            async for token in self.think(user_message):
                result.append(token)
            return "".join(result)

        return asyncio.run(collect())
