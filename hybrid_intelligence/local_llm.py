"""
Local LLM - Local model inference with llama.cpp and other engines.
Supports GGUF models, quantization, and hardware acceleration.
"""
from __future__ import annotations
import asyncio
import logging
import os
import time
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, AsyncGenerator, Dict, List, Optional

logger = logging.getLogger(__name__)


class InferenceEngine(Enum):
    """Inference engines."""
    LLAMA_CPP = "llama_cpp"
    EXLLAMA_V2 = "exllama_v2"
    CT_TRANSFORMERS = "ctransformers"
    MLX = "mlx"  # Apple Silicon
    ONNX_RUNTIME = "onnx_runtime"
    TENSORRT_LLM = "tensorrt_llm"


class QuantizationType(Enum):
    """Model quantization types."""
    Q2_K = "q2_k"
    Q3_K_S = "q3_k_s"
    Q3_K_M = "q3_k_m"
    Q3_K_L = "q3_k_l"
    Q4_0 = "q4_0"
    Q4_K_S = "q4_k_s"
    Q4_K_M = "q4_k_m"
    Q4_K_L = "q4_k_l"
    Q5_0 = "q5_0"
    Q5_K_S = "q5_k_s"
    Q5_K_M = "q5_k_m"
    Q5_K_L = "q5_k_l"
    Q6_K = "q6_k"
    Q8_0 = "q8_0"
    F16 = "f16"
    F32 = "f32"


@dataclass
class LocalModelConfig:
    """Local model configuration."""
    model_id: str
    name: str
    model_path: str
    engine: InferenceEngine = InferenceEngine.LLAMA_CPP
    quantization: QuantizationType = QuantizationType.Q4_K_M

    # Context and generation
    n_ctx: int = 4096
    n_batch: int = 512
    n_gpu_layers: int = -1  # -1 = all
    n_threads: int = 0  # 0 = auto

    # Generation parameters
    temperature: float = 0.7
    top_p: float = 0.9
    top_k: int = 40
    repeat_penalty: float = 1.1
    max_tokens: int = 2048

    # Advanced
    rope_freq_base: float = 10000.0
    rope_freq_scale: float = 1.0
    yarn_ext_factor: float = 1.0
    yarn_attn_factor: float = 1.0
    yarn_beta_fast: float = 32.0
    yarn_beta_slow: float = 1.0

    # Mirostat
    mirostat: int = 0
    mirostat_tau: float = 5.0
    mirostat_eta: float = 0.1

    # Grammar/JSON mode
    grammar: Optional[str] = None
    json_schema: Optional[Dict] = None

    # Performance
    use_mmap: bool = True
    use_mlock: bool = False
    low_vram: bool = False

    def to_llama_cpp_params(self) -> Dict:
        """Convert to llama_cpp Llama constructor params."""
        return {
            "model_path": self.model_path,
            "n_ctx": self.n_ctx,
            "n_batch": self.n_batch,
            "n_gpu_layers": self.n_gpu_layers,
            "n_threads": self.n_threads or None,
            "rope_freq_base": self.rope_freq_base,
            "rope_freq_scale": self.rope_freq_scale,
            "yarn_ext_factor": self.yarn_ext_factor,
            "yarn_attn_factor": self.yarn_attn_factor,
            "yarn_beta_fast": self.yarn_beta_fast,
            "yarn_beta_slow": self.yarn_beta_slow,
            "use_mmap": self.use_mmap,
            "use_mlock": self.use_mlock,
            "low_vram": self.low_vram,
            "verbose": False,
        }

    def to_generation_params(self) -> Dict:
        """Convert to generation params."""
        params = {
            "temperature": self.temperature,
            "top_p": self.top_p,
            "top_k": self.top_k,
            "repeat_penalty": self.repeat_penalty,
            "max_tokens": self.max_tokens,
        }
        if self.mirostat > 0:
            params["mirostat_mode"] = self.mirostat
            params["mirostat_tau"] = self.mirostat_tau
            params["mirostat_eta"] = self.mirostat_eta
        if self.grammar:
            params["grammar"] = self.grammar
        return params


@dataclass
class ModelInfo:
    """Model information."""
    model_id: str
    name: str
    path: str
    size_gb: float
    quantization: str
    architecture: str
    context_window: int
    parameters: str  # e.g., "7B", "13B"
    license: str
    description: str
    requires_gpu: bool = False
    min_ram_gb: float = 4.0


class LocalLLM:
    """
    Local LLM inference wrapper.
    Supports multiple engines and model formats.
    """

    def __init__(self, config: LocalModelConfig):
        self.config = config
        self._model: Any = None
        self._engine_module: Any = None
        self._loaded = False
        self._load_time: Optional[datetime] = None
        self._generation_count = 0
        self._total_tokens = 0
        self._total_time = 0.0

    async def load(self) -> bool:
        """Load the model."""
        if self._loaded:
            return True

        if not os.path.exists(self.config.model_path):
            logger.error(f"Model not found: {self.config.model_path}")
            return False

        try:
            if self.config.engine == InferenceEngine.LLAMA_CPP:
                await self._load_llama_cpp()
            elif self.config.engine == InferenceEngine.EXLLAMA_V2:
                await self._load_exllama_v2()
            elif self.config.engine == InferenceEngine.CT_TRANSFORMERS:
                await self._load_ctransformers()
            elif self.config.engine == InferenceEngine.MLX:
                await self._load_mlx()
            else:
                logger.error(f"Unsupported engine: {self.config.engine}")
                return False

            self._loaded = True
            self._load_time = datetime.now()
            logger.info(f"Loaded local model: {self.config.model_id}")
            return True

        except Exception as e:
            logger.error(f"Failed to load model: {e}")
            return False

    async def _load_llama_cpp(self) -> None:
        """Load with llama.cpp."""
        try:
            from llama_cpp import Llama
            loop = asyncio.get_event_loop()
            self._model = await loop.run_in_executor(
                None,
                lambda: Llama(**self.config.to_llama_cpp_params())
            )
        except ImportError:
            raise RuntimeError("llama-cpp-python not installed. Run: pip install llama-cpp-python")

    async def _load_exllama_v2(self) -> None:
        """Load with exllamav2."""
        try:
            from exllamav2 import ExLlamaV2
            from exllamav2.config import ExLlamaV2Config
            config = ExLlamaV2Config(self.config.model_path)
            self._model = ExLlamaV2(config)
        except ImportError:
            raise RuntimeError("exllamav2 not installed")

    async def _load_ctransformers(self) -> None:
        """Load with ctransformers."""
        try:
            from ctransformers import AutoModelForCausalLM
            loop = asyncio.get_event_loop()
            self._model = await loop.run_in_executor(
                None,
                lambda: AutoModelForCausalLM.from_pretrained(
                    self.config.model_path,
                    model_type="llama",
                    gpu_layers=self.config.n_gpu_layers,
                )
            )
        except ImportError:
            raise RuntimeError("ctransformers not installed")

    async def _load_mlx(self) -> None:
        """Load with MLX (Apple Silicon)."""
        try:
            from mlx_lm import load
            loop = asyncio.get_event_loop()
            self._model, self._tokenizer = await loop.run_in_executor(
                None,
                lambda: load(self.config.model_path)
            )
        except ImportError:
            raise RuntimeError("mlx-lm not installed")

    def is_loaded(self) -> bool:
        return self._loaded

    def unload(self) -> None:
        """Unload model from memory."""
        self._model = None
        self._loaded = False
        logger.info(f"Unloaded model: {self.config.model_id}")

    async def generate(
        self,
        prompt: str,
        system_prompt: str = None,
        stream: bool = False,
        **kwargs
    ) -> Any:
        """Generate text."""
        if not self._loaded:
            await self.load()

        if not self._loaded:
            raise RuntimeError("Model not loaded")

        # Merge config with kwargs
        gen_params = self.config.to_generation_params()
        gen_params.update(kwargs)

        # Format prompt
        full_prompt = self._format_prompt(prompt, system_prompt)

        start_time = time.time()

        try:
            if self.config.engine == InferenceEngine.LLAMA_CPP:
                return await self._generate_llama_cpp(full_prompt, stream, gen_params)
            elif self.config.engine == InferenceEngine.EXLLAMA_V2:
                return await self._generate_exllama_v2(full_prompt, stream, gen_params)
            elif self.config.engine == InferenceEngine.CT_TRANSFORMERS:
                return await self._generate_ctransformers(full_prompt, stream, gen_params)
            elif self.config.engine == InferenceEngine.MLX:
                return await self._generate_mlx(full_prompt, stream, gen_params)
        finally:
            self._generation_count += 1
            self._total_time += time.time() - start_time

    def _format_prompt(self, prompt: str, system_prompt: str = None) -> str:
        """Format prompt for model."""
        # Try to detect model format from name
        name_lower = self.config.name.lower()

        if "llama-3" in name_lower or "llama3" in name_lower:
            # Llama 3 format
            if system_prompt:
                return f"<|begin_of_text|><|start_header_id|>system<|end_header_id|>\n{system_prompt}<|eot_id|><|start_header_id|>user<|end_header_id|>\n{prompt}<|eot_id|><|start_header_id|>assistant<|end_header_id|>\n"
            return f"<|begin_of_text|><|start_header_id|>user<|end_header_id|>\n{prompt}<|eot_id|><|start_header_id|>assistant<|end_header_id|>\n"

        elif "mistral" in name_lower or "mixtral" in name_lower:
            # Mistral format
            if system_prompt:
                return f"<s>[INST] {system_prompt}\n\n{prompt} [/INST]"
            return f"<s>[INST] {prompt} [/INST]"

        elif "phi-3" in name_lower or "phi3" in name_lower:
            # Phi-3 format
            if system_prompt:
                return f"<|system|>\n{system_prompt}<|end|>\n<|user|>\n{prompt}<|end|>\n<|assistant|>\n"
            return f"<|user|>\n{prompt}<|end|>\n<|assistant|>\n"

        elif "gemma" in name_lower:
            # Gemma format
            if system_prompt:
                return f"<start_of_turn>system\n{system_prompt}<end_of_turn>\n<start_of_turn>user\n{prompt}<end_of_turn>\n<start_of_turn>model\n"
            return f"<start_of_turn>user\n{prompt}<end_of_turn>\n<start_of_turn>model\n"

        else:
            # Generic Alpaca/Vicuna format
            if system_prompt:
                return f"<<SYS>>\n{system_prompt}\n<</SYS>>\n\n{prompt}"
            return prompt

    async def _generate_llama_cpp(
        self,
        prompt: str,
        stream: bool,
        params: Dict
    ) -> Any:
        """Generate with llama.cpp."""
        loop = asyncio.get_event_loop()

        if stream:
            def stream_gen():
                for chunk in self._model(prompt, stream=True, **params):
                    yield chunk["choices"][0]["text"]
            return stream_gen()
        else:
            result = await loop.run_in_executor(
                None,
                lambda: self._model(prompt, **params)
            )
            return result["choices"][0]["text"]

    async def _generate_exllama_v2(
        self,
        prompt: str,
        stream: bool,
        params: Dict
    ) -> Any:
        """Generate with exllamav2."""
        # ExLlamaV2 generation
        from exllamav2.generator import ExLlamaV2StreamingGenerator
        generator = ExLlamaV2StreamingGenerator(self._model, self._model.config)
        generator.set_stop_conditions(["</s>", "<|end|>"])

        if stream:
            async def stream_gen():
                for chunk in generator.generate_simple(prompt, **params):
                    yield chunk
            return stream_gen()
        else:
            return generator.generate_simple(prompt, **params)

    async def _generate_ctransformers(
        self,
        prompt: str,
        stream: bool,
        params: Dict
    ) -> Any:
        """Generate with ctransformers."""
        loop = asyncio.get_event_loop()

        if stream:
            def stream_gen():
                for token in self._model(prompt, stream=True, **params):
                    yield token
            return stream_gen()
        else:
            return await loop.run_in_executor(
                None,
                lambda: self._model(prompt, **params)
            )

    async def _generate_mlx(
        self,
        prompt: str,
        stream: bool,
        params: Dict
    ) -> Any:
        """Generate with MLX."""
        from mlx_lm import generate

        if stream:
            async def stream_gen():
                for token in generate(self._model, self._tokenizer, prompt=prompt, **params):
                    yield token
            return stream_gen()
        else:
            loop = asyncio.get_event_loop()
            return await loop.run_in_executor(
                None,
                lambda: generate(self._model, self._tokenizer, prompt=prompt, **params)
            )

    async def embed(self, texts: List[str]) -> List[List[float]]:
        """Generate embeddings (if model supports it)."""
        if not self._loaded:
            await self.load()

        if self.config.engine == InferenceEngine.LLAMA_CPP:
            loop = asyncio.get_event_loop()
            embeddings = []
            for text in texts:
                emb = await loop.run_in_executor(
                    None,
                    lambda: self._model.embed(text)
                )
                embeddings.append(emb)
            return embeddings

        raise NotImplementedError("Embeddings not supported for this engine")

    def get_stats(self) -> Dict:
        """Get inference statistics."""
        return {
            "model_id": self.config.model_id,
            "loaded": self._loaded,
            "load_time": self._load_time.isoformat() if self._load_time else None,
            "generation_count": self._generation_count,
            "total_tokens": self._total_tokens,
            "total_time": self._total_time,
            "avg_tokens_per_sec": self._total_tokens / self._total_time if self._total_time > 0 else 0,
            "config": {
                "engine": self.config.engine.value,
                "quantization": self.config.quantization.value,
                "n_ctx": self.config.n_ctx,
                "n_gpu_layers": self.config.n_gpu_layers,
            }
        }


class ModelDownloader:
    """Downloads models from Hugging Face Hub."""

    @staticmethod
    async def download_model(
        repo_id: str,
        filename: str = None,
        local_dir: str = "./models",
        quantization: QuantizationType = None,
    ) -> str:
        """Download model from HF Hub."""
        try:
            from huggingface_hub import hf_hub_download

            Path(local_dir).mkdir(parents=True, exist_ok=True)

            if filename is None:
                # Auto-select based on quantization
                if quantization:
                    filename = f"*{quantization.value}*.gguf"
                else:
                    filename = "*.gguf"

            loop = asyncio.get_event_loop()
            path = await loop.run_in_executor(
                None,
                lambda: hf_hub_download(
                    repo_id=repo_id,
                    filename=filename,
                    local_dir=local_dir,
                    local_dir_use_symlinks=False,
                )
            )
            return path

        except ImportError:
            raise RuntimeError("huggingface_hub not installed. Run: pip install huggingface_hub")

    @staticmethod
    def list_recommended_models() -> List[ModelInfo]:
        """List recommended models for local inference."""
        return [
            ModelInfo(
                model_id="llama-3-8b-instruct",
                name="Llama 3 8B Instruct",
                path="models/llama-3-8b-instruct-q4_k_m.gguf",
                size_gb=4.7,
                quantization="Q4_K_M",
                architecture="Llama 3",
                context_window=8192,
                parameters="8B",
                license="Meta Llama 3 Community License",
                description="Strong general-purpose model, good for chat and reasoning",
                min_ram_gb=8.0,
            ),
            ModelInfo(
                model_id="llama-3-70b-instruct",
                name="Llama 3 70B Instruct",
                path="models/llama-3-70b-instruct-q4_k_m.gguf",
                size_gb=40.0,
                quantization="Q4_K_M",
                architecture="Llama 3",
                context_window=8192,
                parameters="70B",
                license="Meta Llama 3 Community License",
                description="Very capable model, requires significant RAM/VRAM",
                min_ram_gb=48.0,
                requires_gpu=True,
            ),
            ModelInfo(
                model_id="mistral-7b-instruct",
                name="Mistral 7B Instruct v0.3",
                path="models/mistral-7b-instruct-v0.3-q4_k_m.gguf",
                size_gb=4.4,
                quantization="Q4_K_M",
                architecture="Mistral",
                context_window=32768,
                parameters="7B",
                license="Apache 2.0",
                description="Fast and capable, great for coding and reasoning",
                min_ram_gb=8.0,
            ),
            ModelInfo(
                model_id="phi-3-mini-instruct",
                name="Phi-3 Mini Instruct",
                path="models/phi-3-mini-4k-instruct-q4_k_m.gguf",
                size_gb=2.6,
                quantization="Q4_K_M",
                architecture="Phi-3",
                context_window=4096,
                parameters="3.8B",
                license="MIT",
                description="Small but powerful, excellent for edge devices",
                min_ram_gb=4.0,
            ),
            ModelInfo(
                model_id="gemma-2-9b-instruct",
                name="Gemma 2 9B Instruct",
                path="models/gemma-2-9b-instruct-q4_k_m.gguf",
                size_gb=5.2,
                quantization="Q4_K_M",
                architecture="Gemma 2",
                context_window=8192,
                parameters="9B",
                license="Gemma License",
                description="Google's open model, strong multilingual support",
                min_ram_gb=8.0,
            ),
            ModelInfo(
                model_id="qwen2-7b-instruct",
                name="Qwen2 7B Instruct",
                path="models/qwen2-7b-instruct-q4_k_m.gguf",
                size_gb=4.4,
                quantization="Q4_K_M",
                architecture="Qwen2",
                context_window=32768,
                parameters="7B",
                license="Tongyi Qianwen License",
                description="Strong Chinese/English bilingual, great for coding",
                min_ram_gb=8.0,
            ),
        ]


# Predefined model configurations
RECOMMENDED_CONFIGS = {
    "llama-3-8b-instruct": LocalModelConfig(
        model_id="llama-3-8b-instruct",
        name="Llama 3 8B Instruct",
        model_path="models/llama-3-8b-instruct-q4_k_m.gguf",
        engine=InferenceEngine.LLAMA_CPP,
        quantization=QuantizationType.Q4_K_M,
        n_ctx=8192,
        n_gpu_layers=-1,
    ),
    "mistral-7b-instruct": LocalModelConfig(
        model_id="mistral-7b-instruct",
        name="Mistral 7B Instruct v0.3",
        model_path="models/mistral-7b-instruct-v0.3-q4_k_m.gguf",
        engine=InferenceEngine.LLAMA_CPP,
        quantization=QuantizationType.Q4_K_M,
        n_ctx=32768,
        n_gpu_layers=-1,
    ),
    "phi-3-mini-instruct": LocalModelConfig(
        model_id="phi-3-mini-instruct",
        name="Phi-3 Mini Instruct",
        model_path="models/phi-3-mini-4k-instruct-q4_k_m.gguf",
        engine=InferenceEngine.LLAMA_CPP,
        quantization=QuantizationType.Q4_K_M,
        n_ctx=4096,
        n_gpu_layers=-1,
    ),
    "gemma-2-9b-instruct": LocalModelConfig(
        model_id="gemma-2-9b-instruct",
        name="Gemma 2 9B Instruct",
        model_path="models/gemma-2-9b-instruct-q4_k_m.gguf",
        engine=InferenceEngine.LLAMA_CPP,
        quantization=QuantizationType.Q4_K_M,
        n_ctx=8192,
        n_gpu_layers=-1,
    ),
}