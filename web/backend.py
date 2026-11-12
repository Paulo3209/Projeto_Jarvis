"""
JARVIS Web UI Backend - FastAPI + WebSocket.
Porta 8000. Serve frontend React + API REST + WebSocket tempo real.
"""
from __future__ import annotations
import asyncio
import json
import os
from contextlib import asynccontextmanager
from dataclasses import dataclass, asdict
from datetime import datetime
from typing import Optional, List, Dict, Any

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from core.event_bus import get_event_bus, EventType, UserMessageEvent, StatusChangeEvent
from core.llm_hybrid import get_hybrid_llm, LLMConfig, LLMProvider
from voice.tts_hybrid import get_hybrid_tts, TTSConfig, TTSProvider
from voice.voice_gate import get_voice_gate, VoiceGateConfig, GateMode
from voice.clap_detector import ClapDetector, ClapConfig, calibrate_clap_detector
import sounddevice as sd

# Global clap detector instance
_clap_detector = None


# ==================== MODELS ====================

class ChatMessage(BaseModel):
    role: str  # "user" | "assistant" | "system"
    content: str
    timestamp: Optional[str] = None

class ChatRequest(BaseModel):
    message: str
    personality: str = "default"

class ConfigRequest(BaseModel):
    key: str
    value: Any

class VoiceGateConfigRequest(BaseModel):
    mode: Optional[str] = None  # disabled, verify_all, verify_sensitive
    threshold: Optional[float] = None
    user_id: Optional[str] = None

class TTSConfigRequest(BaseModel):
    provider: Optional[str] = None  # kokoro, edge_tts
    voice: Optional[str] = None

class LLMConfigRequest(BaseModel):
    provider: Optional[str] = None  # ollama, gemini
    model: Optional[str] = None


# ==================== CONNECTION MANAGER ====================

class ConnectionManager:
    """Gerencia conexões WebSocket ativas."""

    def __init__(self):
        self.active_connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)

    async def broadcast(self, message: dict):
        """Envia mensagem para todos conectados."""
        dead = []
        for conn in self.active_connections:
            try:
                await conn.send_json(message)
            except:
                dead.append(conn)
        for d in dead:
            self.disconnect(d)

    async def send_personal(self, websocket: WebSocket, message: dict):
        try:
            await websocket.send_json(message)
        except:
            self.disconnect(websocket)


manager = ConnectionManager()


# ==================== EVENT HANDLERS ====================

async def setup_web_events():
    """Subscreve eventos do EventBus e broadcast via WebSocket."""
    bus = await get_event_bus()

    async def on_user_message(event):
        await manager.broadcast({
            "type": "user_message",
            "data": event.data,
            "timestamp": datetime.now().isoformat()
        })

    async def on_assistant_token(event):
        await manager.broadcast({
            "type": "assistant_token",
            "data": {"token": event.data.get("token", "")},
            "timestamp": datetime.now().isoformat()
        })

    async def on_assistant_complete(event):
        await manager.broadcast({
            "type": "assistant_complete",
            "data": {"response": event.data.get("response", "")},
            "timestamp": datetime.now().isoformat()
        })

    async def on_tool_called(event):
        await manager.broadcast({
            "type": "tool_called",
            "data": event.data,
            "timestamp": datetime.now().isoformat()
        })

    async def on_status_change(event):
        await manager.broadcast({
            "type": "status_change",
            "data": event.data,
            "timestamp": datetime.now().isoformat()
        })

    async def on_error(event):
        await manager.broadcast({
            "type": "error",
            "data": event.data,
            "timestamp": datetime.now().isoformat()
        })

    # Subscreve
    bus.subscribe_async(EventType.USER_MESSAGE, on_user_message)
    bus.subscribe_async(EventType.ASSISTANT_TOKEN, on_assistant_token)
    bus.subscribe_async(EventType.ASSISTANT_RESPONSE_COMPLETE, on_assistant_complete)
    bus.subscribe_async(EventType.TOOL_CALLED, on_tool_called)
    bus.subscribe_async(EventType.STATUS_CHANGE, on_status_change)
    bus.subscribe_async(EventType.ERROR, on_error)


# ==================== LIFESPAN ====================

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    print("[WebUI] Iniciando Web UI...")
    await setup_web_events()
    print("[WebUI] Event handlers registrados")
    yield
    # Shutdown
    print("[WebUI] Encerrando Web UI...")


# ==================== APP ====================

app = FastAPI(
    title="JARVIS Web UI",
    description="Interface Web para JARVIS - Chat, Config, Status",
    version="1.0.0",
    lifespan=lifespan
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Static files (frontend build)
frontend_dir = os.path.join(os.path.dirname(__file__), "frontend", "dist")
if os.path.exists(frontend_dir):
    app.mount("/assets", StaticFiles(directory=os.path.join(frontend_dir, "assets")), name="assets")


# ==================== ROUTES ====================

@app.get("/", response_class=HTMLResponse)
async def root():
    """Serve frontend SPA."""
    index_path = os.path.join(frontend_dir, "index.html")
    if os.path.exists(index_path):
        return FileResponse(index_path)
    return HTMLResponse("""
    <html><body style="font-family: monospace; padding: 2rem; background: #0d1117; color: #c9d1d9;">
        <h1>🤖 JARVIS Web UI</h1>
        <p>Frontend não buildado. Execute: <code>cd web/frontend && npm run build</code></p>
        <h2>API Endpoints:</h2>
        <ul>
            <li><a href="/docs">Swagger UI</a></li>
            <li><a href="/api/status">GET /api/status</a></li>
            <li><a href="/api/chat">POST /api/chat</a></li>
            <li>WS: <code>/ws</code></li>
        </ul>
    </body></html>
    """)


@app.get("/api/status")
async def get_status():
    """Status completo do sistema."""
    try:
        llm = await get_hybrid_llm()
        tts = await get_hybrid_tts()
        gate = await get_voice_gate()

        return {
            "timestamp": datetime.now().isoformat(),
            "llm": llm.get_status(),
            "tts": tts.get_status(),
            "voice_gate": gate.config.mode.value if gate else "not_initialized",
            "microphones": [{"index": i, "name": d["name"]} for i, d in enumerate(sd.query_devices()) if d["max_input_channels"] > 0],
        }
    except Exception as e:
        return {"error": str(e), "timestamp": datetime.now().isoformat()}


@app.post("/api/chat")
async def chat(request: ChatRequest):
    """Envia mensagem para o brain e retorna resposta completa."""
    try:
        from core.brain import Brain
        from core.personality import get_personality

        personality = get_personality(request.personality)
        brain = Brain(personality=personality)

        # Coleta resposta completa
        response_parts = []
        async for token in brain.think(request.message):
            response_parts.append(token)

        return {
            "success": True,
            "response": "".join(response_parts),
            "timestamp": datetime.now().isoformat()
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """WebSocket para tempo real: tokens, tools, status."""
    await manager.connect(websocket)
    try:
        # Envia status inicial
        status = await get_status()
        await websocket.send_json({"type": "init", "data": status})

        while True:
            data = await websocket.receive_json()
            msg_type = data.get("type")

            if msg_type == "chat":
                # Processa chat via brain
                from core.brain import Brain
                from core.personality import get_personality

                personality = get_personality(data.get("personality", "default"))
                brain = Brain(personality=personality)

                # Stream tokens via WebSocket
                async for token in brain.think(data.get("message", "")):
                    await websocket.send_json({
                        "type": "token",
                        "data": {"token": token}
                    })

                await websocket.send_json({"type": "done"})

            elif msg_type == "config":
                # Configuração dinâmica
                await handle_config_websocket(websocket, data.get("config", {}))

            elif msg_type == "ping":
                await websocket.send_json({"type": "pong"})

    except WebSocketDisconnect:
        manager.disconnect(websocket)
    except Exception as e:
        print(f"[WebUI] WS Error: {e}")
        manager.disconnect(websocket)


async def handle_config_websocket(websocket: WebSocket, config: dict):
    """Processa comandos de config via WebSocket."""
    try:
        if "voice_gate" in config:
            gate = await get_voice_gate()
            vg_config = config["voice_gate"]
            if "mode" in vg_config:
                from voice.voice_gate import GateMode
                gate.set_mode(GateMode(vg_config["mode"]))
            if "threshold" in vg_config:
                gate.set_threshold(vg_config["threshold"])
            await websocket.send_json({"type": "config_result", "success": True, "voice_gate": gate.get_status()})

        elif "tts" in config:
            tts = await get_hybrid_tts()
            tts_config = config["tts"]
            if "provider" in tts_config:
                from voice.tts_hybrid import TTSProvider
                tts.current_provider = TTSProvider(tts_config["provider"])
            await websocket.send_json({"type": "config_result", "success": True, "tts": tts.get_status()})

        elif "llm" in config:
            llm = await get_hybrid_llm()
            llm_config = config["llm"]
            if "provider" in llm_config:
                from core.llm_hybrid import LLMProvider
                llm.current_provider = LLMProvider(llm_config["provider"])
            await websocket.send_json({"type": "config_result", "success": True, "llm": llm.get_status()})

        else:
            await websocket.send_json({"type": "config_result", "success": False, "error": "Unknown config section"})

    except Exception as e:
        await websocket.send_json({"type": "config_result", "success": False, "error": str(e)})


@app.get("/api/microphones")
async def list_microphones():
    """Lista microfones disponíveis."""
    devices = []
    for i, d in enumerate(sd.query_devices()):
        if d["max_input_channels"] > 0:
            devices.append({
                "index": i,
                "name": d["name"],
                "channels": d["max_input_channels"],
                "sample_rate": int(d["default_samplerate"])
            })
    return {"microphones": devices}


# ==================== CLAP DETECTOR API ====================

from pydantic import BaseModel

class ClapStartRequest(BaseModel):
    threshold: float = 0.08
    mic_index: Optional[int] = None

class ClapCalibrateRequest(BaseModel):
    duration: float = 10.0

@app.post("/api/clap_detector/start")
async def start_clap_detector(request: ClapStartRequest):
    """Inicia detector de palmas."""
    global _clap_detector

    def on_clap():
        # Emite evento via EventBus
        import asyncio
        asyncio.create_task(_emit_clap_event())

    async def _emit_clap_event():
        bus = await get_event_bus()
        bus.emit(StatusChangeEvent("clap_detected", source="clap_detector"))

    if _clap_detector is None:
        _clap_detector = ClapDetector(ClapConfig(
            rms_threshold=request.threshold,
            microphone_index=request.mic_index
        ))

    _clap_detector.on_double_clap = on_clap
    success = _clap_detector.start()
    return {"success": success, "threshold": request.threshold}


@app.post("/api/clap_detector/stop")
async def stop_clap_detector():
    """Para detector de palmas."""
    global _clap_detector
    if _clap_detector:
        _clap_detector.stop()
        _clap_detector = None
        return {"success": True, "message": "Detector parado"}
    return {"success": False, "message": "Detector não iniciado"}


@app.post("/api/clap_detector/calibrate")
async def calibrate_clap_detector_api(request: ClapCalibrateRequest):
    """Calibra threshold automaticamente."""
    global _clap_detector
    if _clap_detector is None:
        _clap_detector = ClapDetector()

    suggested = await calibrate_clap_detector(_clap_detector, request.duration)
    _clap_detector.set_threshold(suggested)
    return {"success": True, "suggested_threshold": round(suggested, 4)}


@app.get("/api/clap_detector/status")
async def clap_detector_status():
    """Status do detector."""
    global _clap_detector
    if _clap_detector:
        return {"success": True, **_clap_detector.get_status()}
    return {"success": False, "message": "Detector não inicializado"}


# ==================== DOCTOR ====================

@app.get("/api/doctor")
async def doctor():
    """Diagnósticos do sistema (jarvis doctor)."""
    checks = {}

    # Python version
    import sys
    checks["python"] = {
        "version": sys.version.split()[0],
        "ok": sys.version_info >= (3, 10)
    }

    # Dependencies
    deps = [
        ("google-genai", "google.genai"),
        ("faster-whisper", "faster_whisper"),
        ("edge-tts", "edge_tts"),
        ("sounddevice", "sounddevice"),
        ("soundfile", "soundfile"),
        ("psutil", "psutil"),
        ("pyautogui", "pyautogui"),
        ("pygetwindow", "pygetwindow"),
        ("pillow", "PIL"),
        ("opencv-python", "cv2"),
        ("paho-mqtt", "paho.mqtt.client"),
        ("resemblyzer", "resemblyzer"),
        ("librosa", "librosa"),
        ("numpy", "numpy"),
        ("torch", "torch"),
        ("uvicorn", "uvicorn"),
        ("fastapi", "fastapi"),
    ]

    dep_results = {}
    for name, import_name in deps:
        try:
            __import__(import_name)
            dep_results[name] = {"installed": True}
        except ImportError:
            dep_results[name] = {"installed": False}

    checks["dependencies"] = dep_results

    # Ollama
    import aiohttp
    ollama_ok = False
    ollama_models = []
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get("http://localhost:11434/api/tags", timeout=aiohttp.ClientTimeout(total=3)) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    ollama_models = [m["name"] for m in data.get("models", [])]
                    ollama_ok = True
    except:
        pass
    checks["ollama"] = {"running": ollama_ok, "models": ollama_models}

    # Gemini API
    from config.settings import GEMINI_API_KEY
    checks["gemini"] = {"configured": bool(GEMINI_API_KEY)}

    # Microphones
    import sounddevice as sd
    mics = [d for d in sd.query_devices() if d["max_input_channels"] > 0]
    checks["microphones"] = {"count": len(mics), "devices": [d["name"] for d in mics]}

    # Disk space
    import shutil
    total, used, free = shutil.disk_usage(".")
    checks["disk"] = {"free_gb": round(free / (1024**3), 1), "total_gb": round(total / (1024**3), 1)}

    # Memory
    import psutil
    mem = psutil.virtual_memory()
    checks["memory"] = {"available_gb": round(mem.available / (1024**3), 1), "total_gb": round(mem.total / (1024**3), 1)}

    # Overall
    all_ok = (
        checks["python"]["ok"] and
        all(d["installed"] for d in dep_results.values()) and
        (ollama_ok or checks["gemini"]["configured"]) and
        len(mics) > 0
    )
    checks["overall"] = "healthy" if all_ok else "degraded"

    return {"timestamp": datetime.now().isoformat(), "checks": checks}


# ==================== RUN ====================

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="info")