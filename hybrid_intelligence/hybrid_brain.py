"""
Hybrid Brain - Combines cloud and local models with intelligent routing.
Gemini + local LLMs, semantic memory, research agents, offline capability.
"""
from __future__ import annotations
import asyncio
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, AsyncGenerator, Dict, List, Optional

from hybrid_intelligence.model_manager import get_model_manager, ModelManager, ModelConfig, ModelType, ModelCapability
from hybrid_intelligence.semantic_memory import get_semantic_memory, SemanticMemory
from hybrid_intelligence.research_agent import get_research_agent, ResearchAgent, ResearchTask

logger = logging.getLogger(__name__)


class ReasoningMode(Enum):
    """Reasoning modes for hybrid brain."""
    FAST = "fast"              # Quick response, prefer cloud
    BALANCED = "balanced"      # Balance speed/quality
    DEEP = "deep"              # Deep reasoning, use best model
    OFFLINE = "offline"        # Only local models
    RESEARCH = "research"      # Research mode with web search
    CREATIVE = "creative"      # Creative tasks
    CODE = "code"              # Code generation
    ANALYSIS = "analysis"      # Analysis tasks


@dataclass
class HybridConfig:
    """Hybrid brain configuration."""
    default_mode: ReasoningMode = ReasoningMode.BALANCED
    prefer_offline: bool = False
    enable_research: bool = True
    enable_memory: bool = True
    max_tokens: int = 4096
    temperature: float = 0.7
    # Model preferences
    cloud_models: List[str] = field(default_factory=list)
    local_models: List[str] = field(default_factory=list)
    embedding_model: str = "embedding"
    # Fallback
    fallback_to_cloud: bool = True
    fallback_to_local: bool = True
    # Memory
    memory_similarity_threshold: float = 0.7
    max_memory_results: int = 5


@dataclass
class BrainContext:
    """Context for brain processing."""
    user_id: str = "default"
    session_id: str = ""
    conversation_history: List[Dict] = field(default_factory=list)
    relevant_memories: List[Any] = field(default_factory=list)
    active_tools: List[str] = field(default_factory=list)
    mode: ReasoningMode = ReasoningMode.BALANCED
    metadata: Dict = field(default_factory=dict)


@dataclass
class BrainResponse:
    """Brain response."""
    content: str
    mode_used: ReasoningMode
    model_used: str
    tokens_used: int = 0
    duration: float = 0.0
    sources: List[Dict] = field(default_factory=list)
    memories_used: List[str] = field(default_factory=list)
    research_done: bool = False
    confidence: float = 1.0


class HybridBrain:
    """
    Hybrid Brain - Intelligent routing between cloud and local models.
    Combines Gemini, local LLMs, semantic memory, and research agents.
    """

    def __init__(self, config: Optional[HybridConfig] = None):
        self.config = config or HybridConfig()
        self._model_manager: Optional[ModelManager] = None
        self._semantic_memory: Optional[SemanticMemory] = None
        self._research_agent: Optional[ResearchAgent] = None
        self._initialized = False
        self._stats = {
            "total_requests": 0,
            "cloud_requests": 0,
            "local_requests": 0,
            "offline_requests": 0,
            "research_requests": 0,
            "memory_hits": 0,
            "total_tokens": 0,
            "total_time": 0.0,
        }

    async def initialize(self) -> None:
        """Initialize hybrid brain components."""
        if self._initialized:
            return

        # Initialize model manager
        self._model_manager = get_model_manager()

        # Register default models if not already registered
        await self._register_default_models()

        # Initialize semantic memory
        if self.config.enable_memory:
            self._semantic_memory = get_semantic_memory(
                embedding_model=self.config.embedding_model
            )
            await self._semantic_memory.initialize()

        # Initialize research agent
        if self.config.enable_research:
            self._research_agent = get_research_agent()

        self._initialized = True
        logger.info("Hybrid Brain initialized")

    async def _register_default_models(self) -> None:
        """Register default model configurations."""
        from config.settings import GEMINI_API_KEY, MODEL

        # Cloud Gemini
        if GEMINI_API_KEY and "gemini" not in [m.model_id for m in self._model_manager._configs.values()]:
            self._model_manager.register_model(ModelConfig(
                model_id="gemini-default",
                model_type=ModelType.CLOUD_GEMINI,
                name=MODEL,
                capabilities=[
                    ModelCapability.CHAT,
                    ModelCapability.COMPLETION,
                    ModelCapability.REASONING,
                    ModelCapability.CODE,
                    ModelCapability.TOOL_USE,
                    ModelCapability.VISION,
                ],
                priority=10,
                api_key=GEMINI_API_KEY,
                max_tokens=8192,
                context_window=32768,
            ))

        # Local models would be registered here if available
        # Example:
        # self._model_manager.register_model(ModelConfig(
        #     model_id="llama-3-8b-instruct",
        #     model_type=ModelType.LOCAL_LLAMA,
        #     name="Llama 3 8B Instruct",
        #     capabilities=[
        #         ModelCapability.CHAT,
        #         ModelCapability.COMPLETION,
        #         ModelCapability.REASONING,
        #         ModelCapability.CODE,
        #         ModelCapability.OFFLINE,
        #     ],
        #     priority=8,
        #     model_path="models/llama-3-8b-instruct-q4_k_m.gguf",
        # ))

    def _select_model(self, mode: ReasoningMode, required_capabilities: List[ModelCapability] = None) -> Optional[str]:
        """Select best model for mode and capabilities."""
        caps = required_capabilities or []

        if mode == ReasoningMode.OFFLINE:
            caps.append(ModelCapability.OFFLINE)
            return self._model_manager.get_best_model(caps, prefer_offline=True)

        elif mode == ReasoningMode.RESEARCH:
            caps.append(ModelCapability.TOOL_USE)
            caps.append(ModelCapability.REASONING)
            return self._model_manager.get_best_model(caps)

        elif mode == ReasoningMode.CODE:
            caps.append(ModelCapability.CODE)
            return self._model_manager.get_best_model(caps)

        elif mode == ReasoningMode.DEEP:
            caps.append(ModelCapability.REASONING)
            return self._model_manager.get_best_model(caps)

        elif mode == ReasoningMode.FAST:
            return self._model_manager.get_best_model(caps)

        else:  # BALANCED
            return self._model_manager.get_best_model(caps)

    async def think(
        self,
        prompt: str,
        context: Optional[BrainContext] = None,
        mode: ReasoningMode = None,
        system_prompt: str = None,
        stream: bool = False,
        tools: List[Dict] = None,
    ) -> Any:
        """Main thinking method - routes to appropriate model."""
        if not self._initialized:
            await self.initialize()

        context = context or BrainContext()
        mode = mode or context.mode or self.config.default_mode

        start_time = time.time()
        self._stats["total_requests"] += 1

        # Retrieve relevant memories
        memories_used = []
        if self.config.enable_memory and self._semantic_memory:
            memories = await self._retrieve_memories(prompt, context)
            if memories:
                memories_used = [m.id for m in memories]
                context.relevant_memories = memories
                self._stats["memory_hits"] += 1

        # Check if research needed
        research_done = False
        sources = []
        if self.config.enable_research and self._should_research(prompt, mode):
            research_done = True
            self._stats["research_requests"] += 1
            research_result = await self._do_research(prompt, context)
            if research_result:
                sources = research_result.sources
                # Add research findings to prompt
                prompt = f"{prompt}\n\n[Research Findings]\n{research_result.summary}"

        # Select model
        model_id = self._select_model(mode)

        if not model_id:
            raise RuntimeError("No suitable model available")

        # Track model type
        model_config = self._model_manager._configs.get(model_id)
        is_local = model_config and model_config.model_type.value.startswith("local_")
        is_cloud = model_config and model_config.model_type.value.startswith("cloud_")

        if is_local:
            self._stats["local_requests"] += 1
            if self.config.prefer_offline:
                self._stats["offline_requests"] += 1
        elif is_cloud:
            self._stats["cloud_requests"] += 1

        # Build system prompt with context
        full_system = self._build_system_prompt(system_prompt, context, memories_used)

        # Generate response
        try:
            if stream:
                return self._stream_response(
                    prompt, full_system, model_id, mode, start_time,
                    memories_used, sources, research_done
                )
            else:
                response_text = await self._model_manager.generate(
                    prompt=prompt,
                    model_id=model_id,
                    system_prompt=full_system,
                    temperature=self.config.temperature,
                    max_tokens=self.config.max_tokens,
                    tools=tools,
                )

                duration = time.time() - start_time
                self._stats["total_time"] += duration

                return BrainResponse(
                    content=response_text,
                    mode_used=mode,
                    model_used=model_id,
                    duration=duration,
                    sources=[{"title": s.title, "url": s.url, "type": s.source_type.value} for s in sources],
                    memories_used=memories_used,
                    research_done=research_done,
                    confidence=0.9 if not is_local else 0.85,
                )

        except Exception as e:
            logger.error(f"Generation failed: {e}")

            # Try fallback
            if (is_cloud and self.config.fallback_to_local) or (is_local and self.config.fallback_to_cloud):
                fallback_mode = ReasoningMode.OFFLINE if is_cloud else ReasoningMode.FAST
                fallback_model = self._select_model(fallback_mode)
                if fallback_model and fallback_model != model_id:
                    logger.info(f"Falling back to {fallback_model}")
                    return await self.think(prompt, context, fallback_mode, system_prompt, stream, tools)

            raise

    async def _stream_response(
        self,
        prompt: str,
        system_prompt: str,
        model_id: str,
        mode: ReasoningMode,
        start_time: float,
        memories_used: List[str],
        sources: List,
        research_done: bool,
    ) -> AsyncGenerator[str, None]:
        """Stream response from model."""
        # This would stream from the model
        # For now, generate full and yield in chunks
        response_text = await self._model_manager.generate(
            prompt=prompt,
            model_id=model_id,
            system_prompt=system_prompt,
            temperature=self.config.temperature,
            max_tokens=self.config.max_tokens,
        )

        # Yield in chunks
        chunk_size = 50
        for i in range(0, len(response_text), chunk_size):
            yield response_text[i:i+chunk_size]
            await asyncio.sleep(0.01)

    def _build_system_prompt(
        self,
        base_prompt: str,
        context: BrainContext,
        memories_used: List[str],
    ) -> str:
        """Build system prompt with context."""
        parts = []

        if base_prompt:
            parts.append(base_prompt)

        # Add memory context
        if memories_used and self._semantic_memory:
            memory_text = "\n".join([
                f"- {m.content[:200]}" for m in context.relevant_memories[:3]
            ])
            if memory_text:
                parts.append(f"\nRelevant memories:\n{memory_text}")

        # Add conversation context
        if context.conversation_history:
            recent = context.conversation_history[-3:]
            conv_text = "\n".join([f"{m['role']}: {m['content'][:100]}" for m in recent])
            parts.append(f"\nRecent conversation:\n{conv_text}")

        return "\n".join(parts)

    async def _retrieve_memories(self, prompt: str, context: BrainContext) -> List:
        """Retrieve relevant memories."""
        from hybrid_intelligence.semantic_memory import MemoryQuery, MemoryType

        query = MemoryQuery(
            query_text=prompt,
            max_results=self.config.max_memory_results,
            similarity_threshold=self.config.memory_similarity_threshold,
            source=context.user_id,
        )

        results = await self._semantic_memory.retrieve(query)
        return [r.entry for r in results]

    def _should_research(self, prompt: str, mode: ReasoningMode) -> bool:
        """Determine if research is needed."""
        if mode == ReasoningMode.RESEARCH:
            return True

        # Keywords that trigger research
        research_keywords = [
            "pesquise", "busque", "encontre", "o que é", "como fazer",
            "latest", "recent", "news", "atual", "novo", "2024", "2025",
            "compare", "vs", "versus", "melhor", "diferença",
        ]

        prompt_lower = prompt.lower()
        return any(kw in prompt_lower for kw in research_keywords)

    async def _do_research(self, prompt: str, context: BrainContext):
        """Execute research task."""
        task = ResearchTask(
            task_id=f"research_{int(time.time())}",
            query=prompt,
            max_sources=10,
            depth=2,
            source_types=[
                # Would import SourceType
            ] if False else [],  # Simplified
        )
        return await self._research_agent.research(task)

    def get_stats(self) -> Dict:
        """Get brain statistics."""
        stats = self._stats.copy()
        if stats["total_requests"] > 0:
            stats["avg_tokens_per_request"] = stats["total_tokens"] / stats["total_requests"]
            stats["avg_time"] = stats["total_time"] / stats["total_requests"]
            stats["cloud_ratio"] = stats["cloud_requests"] / stats["total_requests"]
            stats["local_ratio"] = stats["local_requests"] / stats["total_requests"]
        return stats

    def get_model_stats(self) -> Dict:
        """Get model manager statistics."""
        if self._model_manager:
            return self._model_manager.get_stats()
        return {}

    def get_memory_stats(self) -> Dict:
        """Get memory statistics."""
        if self._semantic_memory:
            return self._semantic_memory.get_stats()
        return {}

    async def store_memory(
        self,
        content: str,
        memory_type: str = "fact",
        importance: str = "medium",
        tags: List[str] = None,
        metadata: Dict = None,
    ) -> Any:
        """Store memory."""
        if self._semantic_memory:
            from hybrid_intelligence.semantic_memory import MemoryType, MemoryImportance
            return await self._semantic_memory.store(
                content=content,
                memory_type=MemoryType(memory_type),
                importance=MemoryImportance[importance.upper()],
                tags=tags,
                metadata=metadata,
            )
        return None

    async def search_memory(self, query: str, max_results: int = 5) -> List:
        """Search memories."""
        if self._semantic_memory:
            return await self._semantic_memory.search(query, max_results)
        return []

    async def research(self, query: str, max_sources: int = 10, depth: int = 2) -> Any:
        """Execute research."""
        if self._research_agent:
            task = ResearchTask(
                task_id=f"research_{int(time.time())}",
                query=query,
                max_sources=max_sources,
                depth=depth,
            )
            return await self._research_agent.research(task)
        return None

    async def shutdown(self) -> None:
        """Shutdown brain."""
        if self._semantic_memory:
            await self._semantic_memory.shutdown()
        logger.info("Hybrid Brain shutdown")


# Global instance
_hybrid_brain: Optional[HybridBrain] = None


async def get_hybrid_brain(config: Optional[HybridConfig] = None) -> HybridBrain:
    """Get global hybrid brain instance."""
    global _hybrid_brain
    if _hybrid_brain is None:
        _hybrid_brain = HybridBrain(config)
        await _hybrid_brain.initialize()
    return _hybrid_brain