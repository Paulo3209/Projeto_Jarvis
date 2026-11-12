"""
LLM Híbrido: Ollama (local) primário + Gemini (cloud) fallback.
Suporta streaming, tools, e troca automática em falha.
"""
from __future__ import annotations
import asyncio
import json
import os
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import AsyncGenerator, Optional, Dict, Any, List
from enum import Enum

from google import genai
from google.genai._gaos.types.interactions import (
    InteractionSSEEvent, TextDelta, StepDelta, FunctionCallStep,
    InteractionCompletedEvent
)

from config.settings import GEMINI_API_KEY, MODEL, SYSTEM_PROMPT
from core.plugin_system import get_gemini_functions, auto_discover_tools


class LLMProvider(Enum):
    OLLAMA = "ollama"
    GEMINI = "gemini"


@dataclass
class LLMConfig:
    """Configuração do LLM híbrido."""
    primary: LLMProvider = LLMProvider.OLLAMA
    ollama_host: str = "http://localhost:11434"
    ollama_model: str = "gemma3:4b"  # gemma3:4b ou llama3.1:8b
    ollama_timeout: int = 120
    gemini_model: str = MODEL
    gemini_api_key: str = GEMINI_API_KEY
    fallback_on_error: bool = True
    system_prompt: str = SYSTEM_PROMPT


class BaseLLM(ABC):
    """Interface comum para provedores LLM."""

    @abstractmethod
    async def stream_chat(
        self,
        messages: List[Dict[str, str]],
        tools: Optional[List[Dict]] = None,
        **kwargs
    ) -> AsyncGenerator[str, None]:
        """Stream de resposta token por token."""
        pass

    @abstractmethod
    async def execute_tools(
        self,
        tool_calls: List[Dict],
        available_functions: Dict[str, callable]
    ) -> List[Dict]:
        """Executa function calls e retorna resultados."""
        pass

    @abstractmethod
    def is_available(self) -> bool:
        """Verifica se provedor está disponível."""
        pass


class OllamaLLM(BaseLLM):
    """Cliente Ollama local."""

    def __init__(self, config: LLMConfig):
        self.config = config
        self.client = None
        self._session = None

    async def _get_client(self):
        """Lazy init do cliente aiohttp."""
        if self._session is None or self._session.closed:
            import aiohttp
            self._session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=self.config.ollama_timeout)
            )
        return self._session

    async def stream_chat(
        self,
        messages: List[Dict[str, str]],
        tools: Optional[List[Dict]] = None,
        **kwargs
    ) -> AsyncGenerator[str, None]:
        """Stream via Ollama /api/chat."""
        session = await self._get_client()

        payload = {
            "model": self.config.ollama_model,
            "messages": messages,
            "stream": True,
            "options": {
                "temperature": 0.7,
                "top_p": 0.9,
            }
        }

        if tools:
            # Ollama suporta tools no formato OpenAI (function wrapping)
            # Converte do formato Google/Gemini para OpenAI
            openai_tools = []
            for tool in tools:
                if tool.get("type") == "function" and "function" not in tool:
                    # Formato Google: {type: "function", name: "...", description: "...", parameters: {...}}
                    # Formato OpenAI: {type: "function", function: {name: "...", description: "...", parameters: {...}}}
                    openai_tools.append({
                        "type": "function",
                        "function": {
                            "name": tool.get("name"),
                            "description": tool.get("description", ""),
                            "parameters": tool.get("parameters", {"type": "object", "properties": {}})
                        }
                    })
                else:
                    # Já está no formato OpenAI
                    openai_tools.append(tool)
            payload["tools"] = openai_tools
            payload["tool_choice"] = "auto"

        url = f"{self.config.ollama_host}/api/chat"

        try:
            async with session.post(url, json=payload) as resp:
                if resp.status != 200:
                    error = await resp.text()
                    raise RuntimeError(f"Ollama error {resp.status}: {error}")

                async for line in resp.content:
                    if not line:
                        continue
                    try:
                        data = json.loads(line.decode())
                        if "message" in data and "content" in data["message"]:
                            content = data["message"]["content"]
                            if content:
                                yield content
                        if data.get("done", False):
                            break
                    except json.JSONDecodeError:
                        continue
        except asyncio.TimeoutError:
            raise RuntimeError("Ollama timeout")
        except Exception as e:
            raise RuntimeError(f"Ollama connection error: {e}")

    async def execute_tools(
        self,
        tool_calls: List[Dict],
        available_functions: Dict[str, callable]
    ) -> List[Dict]:
        """Executa tools chamadas pelo Ollama."""
        results = []
        for call in tool_calls:
            func_name = call.get("function", {}).get("name")
            func_args = call.get("function", {}).get("arguments", {})
            call_id = call.get("id", "")

            if isinstance(func_args, str):
                try:
                    func_args = json.loads(func_args)
                except:
                    func_args = {}

            if func_name in available_functions:
                try:
                    result = available_functions[func_name](**func_args)
                    results.append({
                        "tool_call_id": call_id,
                        "role": "tool",
                        "name": func_name,
                        "content": json.dumps(result, ensure_ascii=False)
                    })
                except Exception as e:
                    results.append({
                        "tool_call_id": call_id,
                        "role": "tool",
                        "name": func_name,
                        "content": json.dumps({"success": False, "message": str(e)})
                    })
            else:
                results.append({
                    "tool_call_id": call_id,
                    "role": "tool",
                    "name": func_name,
                    "content": json.dumps({"success": False, "message": f"Function {func_name} not found"})
                })
        return results

    async def is_available(self) -> bool:
        """Verifica se Ollama está rodando."""
        import aiohttp
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(f"{self.config.ollama_host}/api/tags", timeout=aiohttp.ClientTimeout(total=3)) as resp:
                    return resp.status == 200
        except:
            return False

    async def close(self):
        if self._session and not self._session.closed:
            await self._session.close()


class GeminiLLM(BaseLLM):
    """Cliente Gemini (cloud) - fallback."""

    def __init__(self, config: LLMConfig):
        self.config = config
        self.client = None
        if config.gemini_api_key:
            self.client = genai.Client(api_key=config.gemini_api_key)

    async def stream_chat(
        self,
        messages: List[Dict[str, str]],
        tools: Optional[List[Dict]] = None,
        **kwargs
    ) -> AsyncGenerator[str, None]:
        """Stream via Gemini API."""
        if not self.client:
            raise RuntimeError("Gemini client not configured")

        # Converte mensagens para formato Gemini
        # Primeira mensagem = system prompt + user
        # Demais = conversation history

        input_text = messages[-1]["content"] if messages else ""
        previous_id = kwargs.get("previous_interaction_id")

        stream_kwargs = {
            "model": self.config.gemini_model,
            "input": input_text,
            "tools": tools or [],
            "stream": True,
        }
        if previous_id:
            stream_kwargs["previous_interaction_id"] = previous_id

        # Use async client for streaming (required for async context manager)
        streaming_client = self.client.aio.interactions.with_streaming_response
        response_ctx = streaming_client.create(**stream_kwargs)

        # Async context manager for streaming (google-genai v2+)
        # The context manager returns an AsyncStreamedAPIResponse which needs parse() to get the AsyncStream
        async with response_ctx as stream:
            async_stream = await stream.parse()
            async for event in async_stream:
                if isinstance(event, InteractionCompletedEvent):
                    break
                elif isinstance(event, StepDelta):
                    if hasattr(event.delta, 'type') and event.delta.type == "text":
                        if hasattr(event.delta, 'text') and event.delta.text:
                            yield event.delta.text

    async def execute_tools(
        self,
        tool_calls: List[Dict],
        available_functions: Dict[str, callable]
    ) -> List[Dict]:
        """Executa tools para Gemini (formato diferente)."""
        results = []
        for call in tool_calls:
            func_name = call.get("name")
            func_args = call.get("arguments", {})
            call_id = call.get("id", "")

            if func_name in available_functions:
                try:
                    result = available_functions[func_name](**func_args)
                    results.append({
                        "type": "function_result",
                        "name": func_name,
                        "call_id": call_id,
                        "result": [{"type": "text", "text": json.dumps(result, ensure_ascii=False)}]
                    })
                except Exception as e:
                    results.append({
                        "type": "function_result",
                        "name": func_name,
                        "call_id": call_id,
                        "result": [{"type": "text", "text": json.dumps({"success": False, "message": str(e)})}]
                    })
        return results

    def is_available(self) -> bool:
        return self.client is not None and bool(self.config.gemini_api_key)


class HybridLLM:
    """
    Orquestrador LLM Híbrido.
    Tenta Ollama primeiro, cai para Gemini em falha.
    """

    def __init__(self, config: LLMConfig = None):
        self.config = config or LLMConfig()
        self.ollama = OllamaLLM(self.config)
        self.gemini = GeminiLLM(self.config)
        self.current_provider: Optional[LLMProvider] = None
        self.available_functions = {}

    async def initialize(self):
        """Descobre tools e verifica provedores."""
        auto_discover_tools()
        self.available_functions = {f["name"]: f for f in get_gemini_functions()}
        print(f"[HybridLLM] Tools carregadas: {len(self.available_functions)}")

        # Verifica disponibilidade
        ollama_ok = await self.ollama.is_available()
        gemini_ok = self.gemini.is_available()
        print(f"[HybridLLM] Ollama: {'[OK]' if ollama_ok else '[ERRO]'} | Gemini: {'[OK]' if gemini_ok else '[ERRO]'}")

        if self.config.primary == LLMProvider.OLLAMA and ollama_ok:
            self.current_provider = LLMProvider.OLLAMA
        elif gemini_ok:
            self.current_provider = LLMProvider.GEMINI
        else:
            raise RuntimeError("Nenhum provedor LLM disponível!")

    def _get_provider(self) -> BaseLLM:
        if self.current_provider == LLMProvider.OLLAMA:
            return self.ollama
        return self.gemini

    async def _maybe_fallback(self, error: Exception):
        """Tenta trocar provedor em caso de erro."""
        if not self.config.fallback_on_error:
            raise error

        if self.current_provider == LLMProvider.OLLAMA:
            print(f"[HybridLLM] Ollama falhou ({error}), tentando Gemini...")
            if self.gemini.is_available():
                self.current_provider = LLMProvider.GEMINI
                return self.gemini
        else:
            print(f"[HybridLLM] Gemini falhou ({error}), tentando Ollama...")
            if await self.ollama.is_available():
                self.current_provider = LLMProvider.OLLAMA
                return self.ollama

        raise error

    async def stream_chat(
        self,
        messages: List[Dict[str, str]],
        **kwargs
    ) -> AsyncGenerator[str, None]:
        """Stream com fallback automático.

        Não envia tools para nenhum provedor (Ollama e Gemini confundem com muitos tools).
        Tools são usadas apenas via Brain class (CLI/Web UI) com Gemini direto.
        """
        # Tools desabilitadas para chat simples - evita que o modelo só pense sem responder
        tools = []

        for attempt in range(2):  # Max 2 tentativas (primário + fallback)
            provider = self._get_provider()
            try:
                async for token in provider.stream_chat(messages, tools, **kwargs):
                    yield token
                return  # Sucesso
            except Exception as e:
                if attempt == 0:
                    fallback_provider = await self._maybe_fallback(e)
                    if fallback_provider:
                        continue
                raise

    async def execute_tools(self, tool_calls: List[Dict]) -> List[Dict]:
        """Executa tools no provedor atual."""
        provider = self._get_provider()
        return await provider.execute_tools(tool_calls, self.available_functions)

    def get_status(self) -> Dict[str, Any]:
        return {
            "current_provider": self.current_provider.value if self.current_provider else None,
            "ollama_available": None,  # async check not available in sync context
            "gemini_available": self.gemini.is_available(),
            "tools_count": len(self.available_functions),
        }

    async def get_status_async(self) -> Dict[str, Any]:
        return {
            "current_provider": self.current_provider.value if self.current_provider else None,
            "ollama_available": await self.ollama.is_available(),
            "gemini_available": self.gemini.is_available(),
            "tools_count": len(self.available_functions),
        }

    async def shutdown(self):
        await self.ollama.close()


# Instância global
_hybrid_llm: Optional[HybridLLM] = None


async def get_hybrid_llm(config: LLMConfig = None) -> HybridLLM:
    global _hybrid_llm
    if _hybrid_llm is None:
        _hybrid_llm = HybridLLM(config)
        await _hybrid_llm.initialize()
    return _hybrid_llm