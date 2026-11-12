"""
Hybrid Intelligence Module - Combines cloud and local models for JARVIS.
Gemini + local LLMs, semantic memory, research agents, offline capability.
"""
from .model_manager import ModelManager, ModelConfig, ModelType, get_model_manager
from .local_llm import LocalLLM, LocalModelConfig, InferenceEngine
from .semantic_memory import SemanticMemory, MemoryEntry, MemoryQuery
from .research_agent import ResearchAgent, ResearchTask, ResearchResult
from .hybrid_brain import HybridBrain, HybridConfig, ReasoningMode

__all__ = [
    "ModelManager",
    "ModelConfig",
    "ModelType",
    "get_model_manager",
    "LocalLLM",
    "LocalModelConfig",
    "InferenceEngine",
    "SemanticMemory",
    "MemoryEntry",
    "MemoryQuery",
    "ResearchAgent",
    "ResearchTask",
    "ResearchResult",
    "HybridBrain",
    "HybridConfig",
    "ReasoningMode",
]