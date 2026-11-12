"""
Model Manager - Manages multiple LLM models (cloud + local).
Handles model selection, fallback, and load balancing.
"""
from __future__ import annotations
import asyncio
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, AsyncGenerator, Dict, List, Optional, Callable

logger = logging.getLogger(__name__)


class ModelType(Enum):
    """Model types."""
    CLOUD_GEMINI = "cloud_gemini"
    CLOUD_OPENAI = "cloud_openai"
    CLOUD_ANTHROPIC = "cloud_anthropic"
    LOCAL_LLAMA = "local_llama"
    LOCAL_MISTRAL = "local_mistral"
    LOCAL_PHI = "local_phi"
    LOCAL_GEMMA = "local_gemma"
    LOCAL_CUSTOM = "local_custom"
    EMBEDDING = "embedding"


class ModelCapability(Enum):
    """Model capabilities."""
    CHAT = "chat"
    COMPLETION = "completion"
    REASONING = "reasoning"
    CODE = "code"
    TOOL_USE = "tool_use"
    VISION = "vision"
    EMBEDDING = "embedding"
    OFFLINE = "offline"


@dataclass
class ModelConfig:
    """Model configuration."""
    model_id: str
    model_type: ModelType
    name: str
    capabilities: List[ModelCapability]
    priority: int = 1  # Higher = preferred
    max_tokens: int = 4096
    context_window: int = 8192
    temperature: float = 0.7
    top_p: float = 0.9
    # Local model settings
    model_path: Optional[str] = None
    n_gpu_layers: int = -1
    n_ctx: int = 4096
    n_batch: int = 512
    # Cloud settings
    api_key: Optional[str] = None
    api_base: Optional[str] = None
    # Performance
    timeout: int = 60
    max_retries: int = 3
    enabled: bool = True


@dataclass
class ModelInstance:
    """Loaded model instance."""
    config: ModelConfig
    client: Any
    loaded_at: datetime
    last_used: datetime
    usage_count: int = 0
    error_count: int = 0
    is_healthy: bool = True


class ModelManager:
    """
    Manages multiple LLM models with intelligent routing.
    Supports cloud models (Gemini, OpenAI, Anthropic) and local models (llama.cpp, etc.)
    """

    def __init__(self):
        self._models: Dict[str, ModelInstance] = {}
        self._configs: Dict[str, ModelConfig] = {}
        self._default_model: Optional[str] = None
        self._fallback_chain: List[str] = []
        self._embedding_model: Optional[str] = None
        self._routing_rules: List[Callable] = []
        self._stats: Dict[str, Dict] = {}

    def register_model(self, config: ModelConfig) -> None:
        """Register a model configuration."""
        self._configs[config.model_id] = config
        if config.capabilities and ModelCapability.EMBEDDING in config.capabilities:
            if not self._embedding_model or config.priority > self._configs[self._embedding_model].priority:
                self._embedding_model = config.model_id

        # Set default if first chat-capable model
        if not self._default_model and ModelCapability.CHAT in config.capabilities:
            self._default_model = config.model_id

        self._rebuild_fallback_chain()
        logger.info(f"Registered model: {config.model_id} ({config.model_type.value})")

    def _rebuild_fallback_chain(self) -> None:
        """Rebuild fallback chain based on priority and health."""
        chat_models = [
            (m.model_id, m.priority)
            for m in self._configs.values()
            if ModelCapability.CHAT in m.capabilities and m.enabled
        ]
        chat_models.sort(key=lambda x: -x[1])
        self._fallback_chain = [m[0] for m in chat_models]

    async def load_model(self, model_id: str) -> bool:
        """Load a model into memory."""
        if model_id in self._models:
            return True

        config = self._configs.get(model_id)
        if not config:
            logger.error(f"Model config not found: {model_id}")
            return False

        try:
            client = await self._create_client(config)
            if client:
                self._models[model_id] = ModelInstance(
                    config=config,
                    client=client,
                    loaded_at=datetime.now(),
                    last_used=datetime.now(),
                )
                logger.info(f"Loaded model: {model_id}")
                return True
        except Exception as e:
            logger.error(f"Failed to load model {model_id}: {e}")

        return False

    async def _create_client(self, config: ModelConfig) -> Any:
        """Create model client based on type."""
        if config.model_type == ModelType.CLOUD_GEMINI:
            from google import genai
            return genai.Client(api_key=config.api_key)

        elif config.model_type in [ModelType.CLOUD_OPENAI, ModelType.CLOUD_ANTHROPIC]:
            # Would use openai or anthropic SDK
            return None

        elif config.model_type in [
            ModelType.LOCAL_LLAMA, ModelType.LOCAL_MISTRAL,
            ModelType.LOCAL_PHI, ModelType.LOCAL_GEMMA, ModelType.LOCAL_CUSTOM
        ]:
            # Use llama.cpp via llama-cpp-python
            try:
                from llama_cpp import Llama
                return Llama(
                    model_path=config.model_path,
                    n_gpu_layers=config.n_gpu_layers,
                    n_ctx=config.n_ctx,
                    n_batch=config.n_batch,
                    verbose=False,
                )
            except ImportError:
                logger.error("llama-cpp-python not installed")
                return None

        elif config.model_type == ModelType.EMBEDDING:
            # Use sentence-transformers
            try:
                from sentence_transformers import SentenceTransformer
                return SentenceTransformer(config.model_path or "all-MiniLM-L6-v2")
            except ImportError:
                logger.error("sentence-transformers not installed")
                return None

        return None

    def get_model(self, model_id: str = None) -> Optional[ModelInstance]:
        """Get loaded model instance."""
        model_id = model_id or self._default_model
        return self._models.get(model_id)

    def get_best_model(
        self,
        required_capabilities: List[ModelCapability] = None,
        prefer_offline: bool = False,
        max_latency: float = None,
    ) -> Optional[str]:
        """Get best model for requirements."""
        candidates = []

        for model_id, config in self._configs.items():
            if not config.enabled:
                continue

            # Check capabilities
            if required_capabilities:
                if not all(cap in config.capabilities for cap in required_capabilities):
                    continue

            # Check offline preference
            if prefer_offline and ModelCapability.OFFLINE not in config.capabilities:
                continue

            # Check if loaded or loadable
            instance = self._models.get(model_id)
            if instance and instance.is_healthy:
                candidates.append((model_id, config.priority, 0))  # loaded = 0 latency
            elif not instance:
                candidates.append((model_id, config.priority, 1))  # not loaded = 1 latency

        if not candidates:
            return None

        # Sort by priority, then by loaded status
        candidates.sort(key=lambda x: (-x[1], x[2]))
        return candidates[0][0]

    async def ensure_model_loaded(self, model_id: str = None) -> Optional[str]:
        """Ensure a model is loaded, return model_id or fallback."""
        model_id = model_id or self._default_model

        if model_id and model_id in self._models:
            instance = self._models[model_id]
            if instance.is_healthy:
                instance.last_used = datetime.now()
                instance.usage_count += 1
                return model_id

        # Try to load preferred model
        if model_id and await self.load_model(model_id):
            return model_id

        # Fallback chain
        for fallback_id in self._fallback_chain:
            if fallback_id != model_id:
                if fallback_id in self._models:
                    instance = self._models[fallback_id]
                    if instance.is_healthy:
                        logger.info(f"Using fallback model: {fallback_id}")
                        return fallback_id
                elif await self.load_model(fallback_id):
                    return fallback_id

        return None

    async def generate(
        self,
        prompt: str,
        model_id: str = None,
        system_prompt: str = None,
        temperature: float = None,
        max_tokens: int = None,
        stream: bool = False,
        tools: List[Dict] = None,
    ) -> Any:
        """Generate response using best available model."""
        model_id = await self.ensure_model_loaded(model_id)
        if not model_id:
            raise RuntimeError("No available models")

        instance = self._models[model_id]
        config = instance.config
        start_time = time.time()

        try:
            if config.model_type == ModelType.CLOUD_GEMINI:
                return await self._generate_gemini(instance, prompt, system_prompt, temperature, max_tokens, stream, tools)

            elif config.model_type in [
                ModelType.LOCAL_LLAMA, ModelType.LOCAL_MISTRAL,
                ModelType.LOCAL_PHI, ModelType.LOCAL_GEMMA, ModelType.LOCAL_CUSTOM
            ]:
                return await self._generate_local(instance, prompt, system_prompt, temperature, max_tokens, stream)

            else:
                raise NotImplementedError(f"Generation not implemented for {config.model_type}")

        except Exception as e:
            instance.error_count += 1
            if instance.error_count > 3:
                instance.is_healthy = False
            raise

    async def _generate_gemini(
        self,
        instance: ModelInstance,
        prompt: str,
        system_prompt: str,
        temperature: float,
        max_tokens: int,
        stream: bool,
        tools: List[Dict],
    ) -> Any:
        """Generate using Gemini."""
        client = instance.client

        contents = []
        if system_prompt:
            contents.append({"role": "user", "parts": [{"text": system_prompt}]})
            contents.append({"role": "model", "parts": [{"text": "Understood."}]})
        contents.append({"role": "user", "parts": [{"text": prompt}]})

        gen_config = {}
        if temperature is not None:
            gen_config["temperature"] = temperature
        if max_tokens is not None:
            gen_config["max_output_tokens"] = max_tokens

        if stream:
            async def stream_gen():
                response = await client.models.generate_content_stream(
                    model=instance.config.name,
                    contents=contents,
                    config=gen_config,
                )
                async for chunk in response:
                    yield chunk.text
            return stream_gen()
        else:
            response = await client.models.generate_content(
                model=instance.config.name,
                contents=contents,
                config=gen_config,
            )
            return response.text

    async def _generate_local(
        self,
        instance: ModelInstance,
        prompt: str,
        system_prompt: str,
        temperature: float,
        max_tokens: int,
        stream: bool,
    ) -> Any:
        """Generate using local model (llama.cpp)."""
        llm = instance.client
        config = instance.config

        # Format prompt
        full_prompt = ""
        if system_prompt:
            full_prompt += f"<<SYS>>\n{system_prompt}\n<</SYS>>\n\n"
        full_prompt += prompt

        if stream:
            def stream_gen():
                for chunk in llm(
                    full_prompt,
                    max_tokens=max_tokens or config.max_tokens,
                    temperature=temperature or config.temperature,
                    top_p=config.top_p,
                    stream=True,
                ):
                    yield chunk["choices"][0]["text"]
            return stream_gen()
        else:
            result = llm(
                full_prompt,
                max_tokens=max_tokens or config.max_tokens,
                temperature=temperature or config.temperature,
                top_p=config.top_p,
            )
            return result["choices"][0]["text"]

    async def embed(self, texts: List[str], model_id: str = None) -> List[List[float]]:
        """Generate embeddings."""
        model_id = model_id or self._embedding_model
        if not model_id:
            raise RuntimeError("No embedding model configured")

        instance = self._models.get(model_id) or (await self.load_model(model_id) and self._models.get(model_id))
        if not instance:
            raise RuntimeError(f"Embedding model not loaded: {model_id}")

        if instance.config.model_type == ModelType.EMBEDDING:
            embeddings = instance.client.encode(texts)
            return embeddings.tolist()

        raise NotImplementedError("Embeddings only supported for embedding models")

    def get_stats(self) -> Dict:
        """Get model statistics."""
        return {
            "registered": len(self._configs),
            "loaded": len(self._models),
            "default": self._default_model,
            "embedding": self._embedding_model,
            "fallback_chain": self._fallback_chain,
            "models": {
                mid: {
                    "type": m.config.model_type.value,
                    "loaded": mid in self._models,
                    "healthy": self._models[mid].is_healthy if mid in self._models else False,
                    "usage": self._models[mid].usage_count if mid in self._models else 0,
                    "errors": self._models[mid].error_count if mid in self._models else 0,
                }
                for mid in self._configs
            }
        }

    def unload_model(self, model_id: str) -> bool:
        """Unload model from memory."""
        if model_id in self._models:
            del self._models[model_id]
            logger.info(f"Unloaded model: {model_id}")
            return True
        return False

    async def shutdown(self) -> None:
        """Shutdown all models."""
        for model_id in list(self._models.keys()):
            self.unload_model(model_id)
        logger.info("Model manager shutdown")


# Global instance
_model_manager: Optional[ModelManager] = None


def get_model_manager() -> ModelManager:
    """Get global model manager."""
    global _model_manager
    if _model_manager is None:
        _model_manager = ModelManager()
    return _model_manager