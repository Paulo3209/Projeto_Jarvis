"""
Semantic Memory - Long-term memory with vector embeddings for JARVIS.
Stores and retrieves information using semantic similarity.
"""
from __future__ import annotations
import asyncio
import json
import logging
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

logger = logging.getLogger(__name__)


class MemoryType(Enum):
    """Types of memories."""
    FACT = "fact"           # Factual information
    EPISODIC = "episodic"   # Experiences/events
    PROCEDURAL = "procedural"  # How-to knowledge
    PREFERENCE = "preference"  # User preferences
    CONVERSATION = "conversation"  # Chat history
    DOCUMENT = "document"   # Document content
    CODE = "code"           # Code snippets
    CONTEXT = "context"     # Contextual information


class MemoryImportance(Enum):
    """Memory importance levels."""
    LOW = 1
    MEDIUM = 2
    HIGH = 3
    CRITICAL = 4


@dataclass
class MemoryEntry:
    """Single memory entry with embedding."""
    id: str
    content: str
    memory_type: MemoryType
    importance: MemoryImportance
    tags: List[str] = field(default_factory=list)
    metadata: Dict = field(default_factory=dict)
    embedding: Optional[List[float]] = None
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)
    access_count: int = 0
    last_accessed: Optional[datetime] = None
    source: str = "user"  # user, system, agent, document
    expires_at: Optional[datetime] = None

    def to_dict(self) -> Dict:
        return {
            "id": self.id,
            "content": self.content,
            "memory_type": self.memory_type.value,
            "importance": self.importance.value,
            "tags": self.tags,
            "metadata": self.metadata,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "access_count": self.access_count,
            "last_accessed": self.last_accessed.isoformat() if self.last_accessed else None,
            "source": self.source,
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
        }

    @classmethod
    def from_dict(cls, data: Dict) -> 'MemoryEntry':
        entry = cls(
            id=data["id"],
            content=data["content"],
            memory_type=MemoryType(data["memory_type"]),
            importance=MemoryImportance(data["importance"]),
            tags=data.get("tags", []),
            metadata=data.get("metadata", {}),
            created_at=datetime.fromisoformat(data["created_at"]),
            updated_at=datetime.fromisoformat(data["updated_at"]),
            access_count=data.get("access_count", 0),
            last_accessed=datetime.fromisoformat(data["last_accessed"]) if data.get("last_accessed") else None,
            source=data.get("source", "user"),
            expires_at=datetime.fromisoformat(data["expires_at"]) if data.get("expires_at") else None,
        )
        entry.embedding = data.get("embedding")
        return entry


@dataclass
class MemoryQuery:
    """Query for memory retrieval."""
    query_text: str
    memory_types: List[MemoryType] = None
    tags: List[str] = None
    min_importance: MemoryImportance = MemoryImportance.LOW
    max_results: int = 10
    similarity_threshold: float = 0.7
    time_range: Tuple[datetime, datetime] = None
    source: str = None

    def to_dict(self) -> Dict:
        return {
            "query_text": self.query_text,
            "memory_types": [t.value for t in self.memory_types] if self.memory_types else None,
            "tags": self.tags,
            "min_importance": self.min_importance.value,
            "max_results": self.max_results,
            "similarity_threshold": self.similarity_threshold,
            "time_range": [t.isoformat() for t in self.time_range] if self.time_range else None,
            "source": self.source,
        }


@dataclass
class MemoryResult:
    """Memory retrieval result."""
    entry: MemoryEntry
    similarity: float
    rank: int


class SemanticMemory:
    """
    Semantic memory system with vector embeddings.
    Supports storage, retrieval, and management of long-term memories.
    """

    def __init__(
        self,
        storage_path: str = "memory/semantic",
        embedding_model: str = None,
        max_memories: int = 100000,
    ):
        self.storage_path = Path(storage_path)
        self.storage_path.mkdir(parents=True, exist_ok=True)
        self.embedding_model = embedding_model
        self.max_memories = max_memories

        self._memories: Dict[str, MemoryEntry] = {}
        self._embeddings: Dict[str, np.ndarray] = {}
        self._index_dirty = False
        self._initialized = False

    async def initialize(self) -> None:
        """Initialize memory system."""
        if self._initialized:
            return

        # Load existing memories
        await self._load_memories()
        self._initialized = True
        logger.info(f"Semantic memory initialized with {len(self._memories)} memories")

    async def _load_memories(self) -> None:
        """Load memories from disk."""
        memory_file = self.storage_path / "memories.jsonl"
        if not memory_file.exists():
            return

        try:
            async with asyncio.open_file(memory_file, 'r') as f:
                async for line in f:
                    try:
                        data = json.loads(line)
                        entry = MemoryEntry.from_dict(data)
                        self._memories[entry.id] = entry
                        if entry.embedding:
                            self._embeddings[entry.id] = np.array(entry.embedding)
                    except Exception as e:
                        logger.error(f"Error loading memory: {e}")
        except Exception as e:
            logger.error(f"Failed to load memories: {e}")

    async def _save_memory(self, entry: MemoryEntry) -> None:
        """Save single memory to disk."""
        memory_file = self.storage_path / "memories.jsonl"
        try:
            async with asyncio.open_file(memory_file, 'a') as f:
                await f.write(json.dumps(entry.to_dict(), ensure_ascii=False) + "\n")
        except Exception as e:
            logger.error(f"Failed to save memory: {e}")

    async def _persist_all(self) -> None:
        """Persist all memories (rewrite file)."""
        memory_file = self.storage_path / "memories.jsonl"
        try:
            async with asyncio.open_file(memory_file, 'w') as f:
                for entry in self._memories.values():
                    await f.write(json.dumps(entry.to_dict(), ensure_ascii=False) + "\n")
        except Exception as e:
            logger.error(f"Failed to persist memories: {e}")

    async def store(
        self,
        content: str,
        memory_type: MemoryType = MemoryType.FACT,
        importance: MemoryImportance = MemoryImportance.MEDIUM,
        tags: List[str] = None,
        metadata: Dict = None,
        source: str = "user",
        expires_in_days: int = None,
    ) -> MemoryEntry:
        """Store a new memory."""
        await self.initialize()

        entry = MemoryEntry(
            id=str(uuid.uuid4())[:12],
            content=content,
            memory_type=memory_type,
            importance=importance,
            tags=tags or [],
            metadata=metadata or {},
            source=source,
        )

        if expires_in_days:
            entry.expires_at = datetime.now() + timedelta(days=expires_in_days)

        # Generate embedding
        if self.embedding_model:
            entry.embedding = await self._generate_embedding(content)
            if entry.embedding:
                self._embeddings[entry.id] = np.array(entry.embedding)

        self._memories[entry.id] = entry
        await self._save_memory(entry)

        # Enforce max memories limit
        await self._enforce_limit()

        return entry

    async def _generate_embedding(self, text: str) -> Optional[List[float]]:
        """Generate embedding for text."""
        try:
            from hybrid_intelligence.model_manager import get_model_manager
            manager = get_model_manager()
            embeddings = await manager.embed([text], self.embedding_model)
            return embeddings[0] if embeddings else None
        except Exception as e:
            logger.error(f"Embedding generation failed: {e}")
            return None

    async def retrieve(self, query: MemoryQuery) -> List[MemoryResult]:
        """Retrieve memories matching query."""
        await self.initialize()

        if not self._memories:
            return []

        # Generate query embedding
        query_embedding = None
        if self.embedding_model:
            query_embedding = await self._generate_embedding(query.query_text)
            if query_embedding:
                query_embedding = np.array(query_embedding)

        results = []

        for entry in self._memories.values():
            # Check expiration
            if entry.expires_at and entry.expires_at < datetime.now():
                continue

            # Filter by memory type
            if query.memory_types and entry.memory_type not in query.memory_types:
                continue

            # Filter by tags
            if query.tags and not any(tag in entry.tags for tag in query.tags):
                continue

            # Filter by importance
            if entry.importance.value < query.min_importance.value:
                continue

            # Filter by source
            if query.source and entry.source != query.source:
                continue

            # Filter by time range
            if query.time_range:
                if entry.created_at < query.time_range[0] or entry.created_at > query.time_range[1]:
                    continue

            # Calculate similarity
            similarity = 1.0
            if query_embedding is not None and entry.id in self._embeddings:
                similarity = self._cosine_similarity(query_embedding, self._embeddings[entry.id])
                if similarity < query.similarity_threshold:
                    continue

            # Boost by importance and recency
            importance_boost = entry.importance.value * 0.1
            recency_boost = self._recency_score(entry.created_at)
            final_score = similarity + importance_boost + recency_boost

            results.append(MemoryResult(entry=entry, similarity=final_score, rank=0))

        # Sort by score
        results.sort(key=lambda r: r.similarity, reverse=True)

        # Assign ranks
        for i, result in enumerate(results):
            result.rank = i + 1

        # Update access stats
        for result in results[:query.max_results]:
            result.entry.access_count += 1
            result.entry.last_accessed = datetime.now()

        return results[:query.max_results]

    def _cosine_similarity(self, a: np.ndarray, b: np.ndarray) -> float:
        """Calculate cosine similarity."""
        return np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b) + 1e-8)

    def _recency_score(self, created_at: datetime) -> float:
        """Calculate recency boost (0-0.2)."""
        age_hours = (datetime.now() - created_at).total_seconds() / 3600
        if age_hours < 1:
            return 0.2
        elif age_hours < 24:
            return 0.15
        elif age_hours < 168:  # 1 week
            return 0.1
        elif age_hours < 720:  # 1 month
            return 0.05
        return 0.0

    async def search(
        self,
        query_text: str,
        max_results: int = 10,
        memory_type: MemoryType = None,
        tags: List[str] = None,
    ) -> List[MemoryResult]:
        """Simple search interface."""
        query = MemoryQuery(
            query_text=query_text,
            max_results=max_results,
            memory_types=[memory_type] if memory_type else None,
            tags=tags,
        )
        return await self.retrieve(query)

    async def get_by_id(self, memory_id: str) -> Optional[MemoryEntry]:
        """Get memory by ID."""
        await self.initialize()
        return self._memories.get(memory_id)

    async def update(self, memory_id: str, **updates) -> bool:
        """Update memory."""
        await self.initialize()
        entry = self._memories.get(memory_id)
        if not entry:
            return False

        if "content" in updates:
            entry.content = updates["content"]
            # Regenerate embedding
            if self.embedding_model:
                entry.embedding = await self._generate_embedding(entry.content)
                if entry.embedding:
                    self._embeddings[entry.id] = np.array(entry.embedding)

        if "tags" in updates:
            entry.tags = updates["tags"]

        if "metadata" in updates:
            entry.metadata.update(updates["metadata"])

        if "importance" in updates:
            entry.importance = updates["importance"]

        entry.updated_at = datetime.now()
        await self._persist_all()
        return True

    async def delete(self, memory_id: str) -> bool:
        """Delete memory."""
        await self.initialize()
        if memory_id in self._memories:
            del self._memories[memory_id]
            self._embeddings.pop(memory_id, None)
            await self._persist_all()
            return True
        return False

    async def _enforce_limit(self) -> None:
        """Enforce maximum memories limit."""
        if len(self._memories) <= self.max_memories:
            return

        # Remove lowest importance, least accessed, oldest
        sorted_memories = sorted(
            self._memories.values(),
            key=lambda m: (
                m.importance.value,
                m.access_count,
                m.created_at.timestamp()
            )
        )

        to_remove = len(self._memories) - self.max_memories
        for entry in sorted_memories[:to_remove]:
            del self._memories[entry.id]
            self._embeddings.pop(entry.id, None)

        await self._persist_all()

    async def cleanup_expired(self) -> int:
        """Remove expired memories."""
        await self.initialize()
        now = datetime.now()
        expired = [
            mid for mid, entry in self._memories.items()
            if entry.expires_at and entry.expires_at < now
        ]
        for mid in expired:
            del self._memories[mid]
            self._embeddings.pop(mid, None)

        if expired:
            await self._persist_all()

        return len(expired)

    def get_stats(self) -> Dict:
        """Get memory statistics."""
        type_counts = {}
        importance_counts = {}
        source_counts = {}

        for entry in self._memories.values():
            type_counts[entry.memory_type.value] = type_counts.get(entry.memory_type.value, 0) + 1
            importance_counts[entry.importance.name] = importance_counts.get(entry.importance.name, 0) + 1
            source_counts[entry.source] = source_counts.get(entry.source, 0) + 1

        return {
            "total_memories": len(self._memories),
            "with_embeddings": len(self._embeddings),
            "by_type": type_counts,
            "by_importance": importance_counts,
            "by_source": source_counts,
            "max_memories": self.max_memories,
            "embedding_model": self.embedding_model,
        }

    async def export(self, filepath: str) -> bool:
        """Export memories to file."""
        try:
            data = [entry.to_dict() for entry in self._memories.values()]
            async with asyncio.open_file(filepath, 'w') as f:
                await f.write(json.dumps(data, ensure_ascii=False, indent=2))
            return True
        except Exception as e:
            logger.error(f"Export failed: {e}")
            return False

    async def import_memories(self, filepath: str) -> int:
        """Import memories from file."""
        try:
            async with asyncio.open_file(filepath, 'r') as f:
                content = await f.read()
                data = json.loads(content)

            imported = 0
            for item in data:
                entry = MemoryEntry.from_dict(item)
                self._memories[entry.id] = entry
                if entry.embedding:
                    self._embeddings[entry.id] = np.array(entry.embedding)
                imported += 1

            await self._persist_all()
            return imported

        except Exception as e:
            logger.error(f"Import failed: {e}")
            return 0

    async def shutdown(self) -> None:
        """Shutdown memory system."""
        await self._persist_all()
        logger.info("Semantic memory shutdown")


# Global instance
_semantic_memory: Optional[SemanticMemory] = None


def get_semantic_memory(
    storage_path: str = "memory/semantic",
    embedding_model: str = None,
) -> SemanticMemory:
    """Get global semantic memory instance."""
    global _semantic_memory
    if _semantic_memory is None:
        _semantic_memory = SemanticMemory(storage_path, embedding_model)
    return _semantic_memory