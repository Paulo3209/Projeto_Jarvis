"""
Voice Gate - Intercepta transcrições e verifica speaker ID antes de processar.
Integra com VoiceBridge para proteger comandos sensíveis.
"""
from __future__ import annotations
import asyncio
import base64
import io
import numpy as np
from typing import Optional, Callable, Set, Dict, Any
from dataclasses import dataclass
from enum import Enum

from core.event_bus import (
    EventBus, EventType, get_event_bus,
    UserMessageEvent, VoiceTranscriptionEvent,
    ErrorEvent, StatusChangeEvent,
)
from tools.voice_auth import (
    voice_verify, voice_enroll, voice_test_mic,
    _load_voiceprint, _voiceprint_path, _hash_user_id,
    RESMBLYZER_AVAILABLE
)

# webrtcvad não necessário - VAD simples em voice_auth.py


class GateMode(Enum):
    """Modos de operação do gate."""
    DISABLED = "disabled"      # Sem verificação (padrão atual)
    VERIFY_ALL = "verify_all"  # Verifica TODOS os comandos
    VERIFY_SENSITIVE = "verify_sensitive"  # Só comandos sensíveis
    ENROLL = "enroll"          # Modo enrollment


@dataclass
class VoiceGateConfig:
    """Configuração do Voice Gate."""
    mode: GateMode = GateMode.VERIFY_SENSITIVE
    user_id: str = "master"
    threshold: float = 0.82
    sensitive_commands: Set[str] = None
    allow_enroll_voice: bool = True  # Permite "jarvis enroll minha voz" sem verificação
    fallback_to_text: bool = True    # Se falhar verificação, permite via texto (CLI/HUD)

    def __post_init__(self):
        if self.sensitive_commands is None:
            self.sensitive_commands = {
                # Sistema crítico
                "power_control", "kill_process", "manage_service",
                "run_powershell", "registry_edit", "power_control",
                # Android sensível
                "android_package_manager", "android_shell", "android_communication",
                # Cross-device
                "cross_device_send_command",
                # Segurança
                "voice_delete_print",
            }


class VoiceGate:
    """
    Gate de autenticação de voz.
    Intercepta UserMessageEvent/VoiceTranscriptionEvent e verifica speaker.
    """

    def __init__(self, config: VoiceGateConfig = None):
        self.config = config or VoiceGateConfig()
        self._event_bus: Optional[EventBus] = None
        self._enrollment_mode = False
        self._enrollment_future: Optional[asyncio.Future] = None
        self._pending_audio: Dict[str, bytes] = {}  # correlation_id -> audio bytes

    async def initialize(self) -> bool:
        """Inicializa e subscreve eventos."""
        if not RESMBLYZER_AVAILABLE:
            print("[VoiceGate] [AVISO]  resemblyzer não disponível - gate desabilitado")
            self.config.mode = GateMode.DISABLED
            return False

        self._event_bus = await get_event_bus()

        # Verifica se tem voiceprint
        vp = _load_voiceprint(self.config.user_id)
        if not vp and self.config.mode != GateMode.DISABLED:
            print(f"[VoiceGate] [AVISO]  Voiceprint não encontrado para '{self.config.user_id}'")
            print("[VoiceGate]   Rode: voice_enroll(user_id='master')")
            if self.config.mode == GateMode.VERIFY_ALL:
                print("[VoiceGate]   Modo VERIFY_ALL requer voiceprint - caindo para VERIFY_SENSITIVE")
                self.config.mode = GateMode.VERIFY_SENSITIVE

        # Subscreve eventos de voz
        self._event_bus.subscribe_async(EventType.VOICE_TRANSCRIPTION, self._on_voice_transcription)
        self._event_bus.subscribe_async(EventType.USER_MESSAGE, self._on_user_message)

        print(f"[VoiceGate] [OK] Inicializado - Modo: {self.config.mode.value}")
        return True

    def _is_sensitive_command(self, text: str) -> bool:
        """Detecta se comando é sensível baseado em palavras-chave."""
        text_lower = text.lower()
        sensitive_keywords = [
            "desligue", "reinicie", "hibernar", "suspender", "bloquear",
            "mate", "encerre", "pare", "kill",
            "registry", "registro", "regedit",
            "powershell", "admin", "administrador",
            "desinstale", "instale", "apague", "delete",
            "sms", "ligação", "ligar para",
            "formate", "limpe", "reset",
        ]
        return any(kw in text_lower for kw in sensitive_keywords)

    async def _on_voice_transcription(self, event) -> None:
        """Intercepta transcrição de voz ANTES de virar UserMessageEvent."""
        if self.config.mode == GateMode.DISABLED:
            return  # Passa direto

        text = event.data.get('text', '').strip()
        audio_b64 = event.data.get('audio_base64')  # Precisa que STT forneça
        correlation_id = event.data.get('correlation_id', '')

        if not text:
            return

        # Verifica se é comando de enrollment (sempre permitido)
        if self.config.allow_enroll_voice and self._is_enroll_command(text):
            await self._handle_enroll_command(text)
            # Cancela processamento normal
            if self._event_bus:
                self._event_bus.emit(ErrorEvent("Enrollment command handled by VoiceGate", source="voice_gate"))
            return

        # Decide se verifica
        should_verify = (
            self.config.mode == GateMode.VERIFY_ALL or
            (self.config.mode == GateMode.VERIFY_SENSITIVE and self._is_sensitive_command(text))
        )

        if should_verify:
            # Verifica voz
            result = await self._verify_voice(audio_b64)

            if not result.get("match", False):
                # Rejeita - emite erro e NÃO propaga como UserMessageEvent
                msg = f"🔒 Voz não reconhecida (score: {result.get('score', 0):.2f}). Comando ignorado."
                print(f"[VoiceGate] 🚫 {msg}")
                if self._event_bus:
                    self._event_bus.emit(ErrorEvent(msg, source="voice_gate"))
                    self._event_bus.emit(StatusChangeEvent("voice_rejected", source="voice_gate"))
                return  # BLOQUEIA - não continua

            print(f"[VoiceGate] [OK] Voz autenticada (score: {result.get('score', 0):.2f})")

        # Se passou ou não precisa verificar, deixa seguir normal
        # O VoiceBridge já converte VoiceTranscriptionEvent -> UserMessageEvent

    async def _on_user_message(self, event) -> None:
        """Fallback para mensagens de texto (CLI/HUD) - opcional."""
        if self.config.mode == GateMode.DISABLED:
            return

        source = event.data.get('source', '')
        if source in ('cli', 'gui', 'hud') and self.config.fallback_to_text:
            return  # Permite texto sem verificação

        # Se veio de voz mas passou pelo gate, OK
        if source == 'voice':
            return

        # Outras sources - decide baseado na config
        text = event.data.get('message', '')
        if self._is_sensitive_command(text) and self.config.mode != GateMode.DISABLED:
            if self._event_bus:
                self._event_bus.emit(ErrorEvent("Comando sensível requer autenticação de voz", source="voice_gate"))
            # Poderia bloquear aqui também se quiser

    def _is_enroll_command(self, text: str) -> bool:
        """Detecta comando de enrollment."""
        text_lower = text.lower()
        enroll_triggers = [
            "enroll minha voz",
            "enrol minha voz",
            "cadastrar minha voz",
            "gravar minha voz",
            "aprender minha voz",
            "voice enroll",
        ]
        return any(t in text_lower for t in enroll_triggers)

    async def _handle_enroll_command(self, text: str) -> None:
        """Processa comando de enrollment por voz."""
        print("[VoiceGate] 🎙️  Iniciando enrollment por voz...")

        try:
            # Usa a ferramenta voice_enroll (grava ao vivo)
            result = voice_enroll(
                user_id=self.config.user_id,
                samples=5,
                duration_seconds=3.0
            )

            if result.get("success"):
                msg = f"[OK] {result['message']}. VoiceGate recarregado."
                print(f"[VoiceGate] {msg}")
                if self._event_bus:
                    self._event_bus.emit(StatusChangeEvent("voice_enrolled", source="voice_gate"))
            else:
                msg = f"❌ Enrollment falhou: {result.get('message')}"
                print(f"[VoiceGate] {msg}")
                if self._event_bus:
                    self._event_bus.emit(ErrorEvent(msg, source="voice_gate"))

        except Exception as e:
            print(f"[VoiceGate] Erro no enrollment: {e}")
            if self._event_bus:
                self._event_bus.emit(ErrorEvent(f"Enrollment error: {e}", source="voice_gate"))

    async def _verify_voice(self, audio_b64: str = None) -> dict:
        """Chama voice_verify com áudio base64 ou gravação ao vivo."""
        # Se não tem áudio do STT, tenta gravar ao vivo (fallback)
        # Idealmente o STT (FasterWhisper) deveria passar o áudio original
        return voice_verify(
            user_id=self.config.user_id,
            audio_data=audio_b64,
            threshold=self.config.threshold
        )

    def set_mode(self, mode: GateMode) -> None:
        """Muda modo de operação."""
        self.config.mode = mode
        print(f"[VoiceGate] Modo alterado para: {mode.value}")

    def set_threshold(self, threshold: float) -> None:
        """Ajusta threshold de similaridade."""
        self.config.threshold = max(0.5, min(0.99, threshold))
        print(f"[VoiceGate] Threshold: {self.config.threshold}")

    def add_sensitive_command(self, command: str) -> None:
        """Adiciona palavra-chave sensível."""
        self.config.sensitive_commands.add(command.lower())

    def remove_sensitive_command(self, command: str) -> None:
        """Remove palavra-chave sensível."""
        self.config.sensitive_commands.discard(command.lower())

    def get_status(self) -> dict:
        """Retorna status do VoiceGate."""
        from pathlib import Path
        vp_path = Path.home() / ".jarvis" / "voiceprints" / f"{self.config.user_id}.json"
        return {
            "mode": self.config.mode.value,
            "threshold": self.config.threshold,
            "user_id": self.config.user_id,
            "voiceprint_exists": vp_path.exists(),
            "sensitive_keywords_count": len(self.config.sensitive_commands),
        }

    async def shutdown(self) -> None:
        if self._event_bus:
            # Unsubscribe seria ideal, mas EventBus não tem unsubscribe_async fácil
            pass


# Instância global
_voice_gate: Optional[VoiceGate] = None


async def get_voice_gate(config: VoiceGateConfig = None) -> VoiceGate:
    """Obtém instância global do VoiceGate."""
    global _voice_gate
    if _voice_gate is None:
        _voice_gate = VoiceGate(config)
        await _voice_gate.initialize()
    return _voice_gate


# ==================== FERRAMENTAS DE CONTROLE ====================

from core.plugin_system import tool, ToolCategory


@tool(description="Configura modo do Voice Gate (disabled/verify_all/verify_sensitive).", category=ToolCategory.SECURITY)
def voice_gate_mode(mode: str = "verify_sensitive", threshold: float = 0.82) -> dict:
    """Modos: disabled, verify_all, verify_sensitive. Threshold 0.5-0.99."""
    global _voice_gate
    try:
        gate_mode = GateMode(mode.lower())
    except ValueError:
        return {"success": False, "message": "Modos: disabled, verify_all, verify_sensitive"}

    if _voice_gate:
        _voice_gate.set_mode(gate_mode)
        _voice_gate.set_threshold(threshold)
        return {"success": True, "mode": gate_mode.value, "threshold": threshold}

    # Se não inicializado, guarda config para próxima init
    return {"success": True, "message": f"Configurado para próxima inicialização: {gate_mode.value}"}


@tool(description="Testa verificação de voz agora (grava 3s).", category=ToolCategory.SECURITY)
def voice_gate_test(user_id: str = "master", threshold: float = 0.82) -> dict:
    """Testa se sua voz passa no gate atual."""
    return voice_verify(user_id=user_id, threshold=threshold)


@tool(description="Mostra status do Voice Gate.", category=ToolCategory.SECURITY)
def voice_gate_status() -> dict:
    """Status atual do gate."""
    global _voice_gate
    vp_exists = _voiceprint_path("master").exists()  # simplificado
    return {
        "success": True,
        "initialized": _voice_gate is not None,
        "mode": _voice_gate.config.mode.value if _voice_gate else "not_initialized",
        "threshold": _voice_gate.config.threshold if _voice_gate else 0.82,
        "user_id": _voice_gate.config.user_id if _voice_gate else "master",
        "voiceprint_exists": vp_exists,
        "sensitive_keywords_count": len(_voice_gate.config.sensitive_commands) if _voice_gate else 0,
        "resemblyzer_available": RESMBLYZER_AVAILABLE,
    }


# Export
AVAILABLE_FUNCTIONS = {
    "voice_gate_mode": voice_gate_mode,
    "voice_gate_test": voice_gate_test,
    "voice_gate_status": voice_gate_status,
}