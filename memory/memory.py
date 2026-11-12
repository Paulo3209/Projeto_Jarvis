import asyncio
import sqlite3
from datetime import datetime
from pathlib import Path
from core.event_bus import (
    EventBus,
    EventType,
    MemorySavedEvent,
    MemoryRecalledEvent,
    get_event_bus,
)
from core.plugin_system import tool, ToolCategory

DB = Path(__file__).resolve().parent / "jarvis_memory.db"


def _connect():
    conn = sqlite3.connect(DB)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS memories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            content TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
    """)
    return conn


@tool(
    description="Salva uma informação que o usuário pediu para lembrar.",
    category=ToolCategory.MEMORY,
)
def save_memory(content: str) -> dict:
    """Salva uma memória permanente.

    Args:
        content: Conteúdo a ser memorizado
    """
    conn = _connect()
    conn.execute(
        "INSERT INTO memories(content, created_at) VALUES (?, ?)",
        (content, datetime.now().isoformat(timespec="seconds"))
    )
    conn.commit()
    conn.close()

    # Emit event (fire-and-forget)
    _emit_memory_saved(content)

    return {"success": True, "message": "Memória salva."}


@tool(
    description="Procura memórias salvas relacionadas a uma consulta.",
    category=ToolCategory.MEMORY,
)
def recall_memory(query: str) -> dict:
    """Busca memórias relacionadas a um termo.

    Args:
        query: Termo de busca
    """
    conn = _connect()
    rows = conn.execute(
        "SELECT content, created_at FROM memories WHERE content LIKE ? ORDER BY id DESC LIMIT 10",
        (f"%{query}%",)
    ).fetchall()
    conn.close()

    memories = [{"content": r[0], "created_at": r[1]} for r in rows]

    # Emit event (fire-and-forget)
    _emit_memory_recalled(query, memories)

    return {
        "success": True,
        "memories": memories
    }


def _emit_memory_saved(content: str) -> None:
    """Emit memory saved event (sync, fire-and-forget)."""
    try:
        bus = EventBus._instance
        if bus:
            bus.emit(MemorySavedEvent(content, source="memory"))
    except Exception:
        pass


def _emit_memory_recalled(query: str, memories: list) -> None:
    """Emit memory recalled event (sync, fire-and-forget)."""
    try:
        bus = EventBus._instance
        if bus:
            bus.emit(MemoryRecalledEvent(query, memories, source="memory"))
    except Exception:
        pass


# Async versions for future use
async def save_memory_async(content: str):
    """Async version of save_memory."""
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(None, save_memory, content)
    return result


async def recall_memory_async(query: str):
    """Async version of recall_memory."""
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(None, recall_memory, query)
    return result