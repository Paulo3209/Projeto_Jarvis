"""
Voice Authentication - Speaker Recognition para JARVIS.
Usa resemblyzer (embedding de voz) + VAD simples baseado em energia.
Seguro: armazena apenas embedding (hash irreversível), não áudio bruto.
"""
import os
import json
import hashlib
import base64
from pathlib import Path
from datetime import datetime
from typing import Optional, Tuple
from core.plugin_system import tool, ToolCategory

try:
    import numpy as np
    from resemblyzer import VoiceEncoder, preprocess_wav
    RESMBLYZER_AVAILABLE = True
except ImportError:
    RESMBLYZER_AVAILABLE = False

# Configuração
VOICEPRINT_DIR = Path(__file__).resolve().parents[1] / "memory" / "voiceprints"
VOICEPRINT_DIR.mkdir(parents=True, exist_ok=True)

ENCODER: Optional["VoiceEncoder"] = None

SAMPLE_RATE = 16000
FRAME_DURATION_MS = 30
FRAME_SIZE = int(SAMPLE_RATE * FRAME_DURATION_MS / 1000)

# VAD simples baseado em energia (fallback sem webrtcvad)
def _vad_filter(audio: np.ndarray, sample_rate: int = SAMPLE_RATE) -> np.ndarray:
    """Filtra apenas frames com voz baseado em energia (RMS)."""
    if len(audio) == 0:
        return audio

    # Calcula RMS por frame
    rms_values = []
    for i in range(0, len(audio), FRAME_SIZE):
        frame = audio[i:i + FRAME_SIZE]
        if len(frame) < FRAME_SIZE:
            frame = np.pad(frame, (0, FRAME_SIZE - len(frame)))
        rms = np.sqrt(np.mean(frame**2))
        rms_values.append(rms)

    if not rms_values:
        return audio

    # Threshold adaptativo: 30% do RMS máximo
    max_rms = max(rms_values)
    threshold = max_rms * 0.3

    # Filtra frames acima do threshold
    voiced_frames = []
    for i, rms in enumerate(rms_values):
        if rms > threshold:
            start = i * FRAME_SIZE
            end = start + FRAME_SIZE
            if end <= len(audio):
                voiced_frames.append(audio[start:end])
            else:
                voiced_frames.append(audio[start:])

    if voiced_frames:
        return np.concatenate(voiced_frames)
    return audio  # fallback: retorna original se nada detectado


def _get_encoder() -> "VoiceEncoder":
    global ENCODER
    if ENCODER is None:
        if not RESMBLYZER_AVAILABLE:
            raise RuntimeError("resemblyzer não instalado. pip install resemblyzer webrtcvad")
        ENCODER = VoiceEncoder()
    return ENCODER


def _hash_user_id(user_id: str) -> str:
    """Hash do user_id para nome do arquivo (não expõe identidade)."""
    return hashlib.sha256(user_id.encode()).hexdigest()[:16]


def _voiceprint_path(user_id: str) -> Path:
    return VOICEPRINT_DIR / f"{_hash_user_id(user_id)}.json"


def _save_voiceprint(user_id: str, embedding: np.ndarray, metadata: dict) -> None:
    """Salva voiceprint criptografado (apenas embedding + metadados)."""
    data = {
        "user_id_hash": _hash_user_id(user_id),
        "embedding": embedding.tolist(),
        "created_at": datetime.now().isoformat(),
        "updated_at": datetime.now().isoformat(),
        "version": "1.0",
        "metadata": metadata  # ex: {"device": "mic_principal", "samples": 5}
    }
    _voiceprint_path(user_id).write_text(json.dumps(data), encoding="utf-8")


def _load_voiceprint(user_id: str) -> Optional[dict]:
    """Carrega voiceprint se existir."""
    path = _voiceprint_path(user_id)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _compute_embedding(audio: np.ndarray) -> np.ndarray:
    """Gera embedding 256-d do áudio."""
    encoder = _get_encoder()
    return encoder.embed_utterance(audio)


def _compare_embeddings(emb1: np.ndarray, emb2: np.ndarray) -> float:
    """Similaridade cosseno entre embeddings (0-1, >0.8 = mesmo locutor)."""
    return float(np.dot(emb1, emb2) / (np.linalg.norm(emb1) * np.linalg.norm(emb2)))


def _vad_filter(audio: np.ndarray, sample_rate: int = SAMPLE_RATE) -> np.ndarray:
    """Filtra apenas frames com voz (remove silêncio)."""
    if VAD is None:
        return audio

    voiced_frames = []
    for i in range(0, len(audio), FRAME_SIZE):
        frame = audio[i:i + FRAME_SIZE]
        if len(frame) < FRAME_SIZE:
            frame = np.pad(frame, (0, FRAME_SIZE - len(frame)))
        # webrtcvad precisa de int16
        frame_int16 = (frame * 32767).astype(np.int16).tobytes()
        if VAD.is_speech(frame_int16, sample_rate):
            voiced_frames.append(frame)

    if voiced_frames:
        return np.concatenate(voiced_frames)
    return audio  # fallback


# ==================== FERRAMENTAS ====================

@tool(
    description="Enrola sua voz para autenticação (execute uma vez por dispositivo/microfone).",
    category=ToolCategory.SECURITY,
)
def voice_enroll(user_id: str = "master", samples: int = 5, duration_seconds: float = 3.0) -> dict:
    """
    Grava N amostras de voz e cria voiceprint.

    Args:
        user_id: Identificador do usuário (ex: "master", "paulo")
        samples: Número de amostras para gravar (padrão 5)
        duration_seconds: Duração de cada gravação (padrão 3s)
    """
    if not RESMBLYZER_AVAILABLE:
        return {"success": False, "message": "Dependências não instaladas: pip install resemblyzer webrtcvad numpy"}

    try:
        import sounddevice as sd
        import soundfile as sf
    except ImportError:
        return {"success": False, "message": "sounddevice/soundfile necessários: pip install sounddevice soundfile"}

    print(f"\n🎙️  ENROLLMENT DE VOZ - Usuário: {user_id}")
    print(f"   Gravar {samples} amostras de {duration_seconds}s cada")
    print(f"   Fale naturalmente: 'JARVIS é meu assistente pessoal'")
    print(f"   Pressione ENTER para iniciar cada gravação...\n")

    embeddings = []

    for i in range(samples):
        input(f"   [{i+1}/{samples}] Pressione ENTER e fale...")

        # Grava
        recording = sd.rec(
            int(duration_seconds * SAMPLE_RATE),
            samplerate=SAMPLE_RATE,
            channels=1,
            dtype='float32'
        )
        sd.wait()
        audio = recording.flatten()

        # VAD filter
        audio = _vad_filter(audio)

        if len(audio) < SAMPLE_RATE * 0.5:
            print(f"   ⚠️  Áudio muito curto, tente novamente")
            continue

        # Embedding
        emb = _compute_embedding(audio)
        embeddings.append(emb)
        print(f"   ✅ Amostra {i+1} capturada (embedding: {emb.shape})")

    if len(embeddings) < 3:
        return {"success": False, "message": f"Poucas amostras válidas ({len(embeddings)}). Mínimo 3."}

    # Média dos embeddings (mais robusto)
    mean_embedding = np.mean(embeddings, axis=0)
    mean_embedding = mean_embedding / np.linalg.norm(mean_embedding)

    # Salva
    _save_voiceprint(user_id, mean_embedding, {
        "device": sd.query_devices(sd.default.device[0])['name'] if hasattr(sd, 'query_devices') else "default",
        "samples": len(embeddings),
        "sample_rate": SAMPLE_RATE,
        "duration_per_sample": duration_seconds
    })

    return {
        "success": True,
        "message": f"Voiceprint criado para '{user_id}' com {len(embeddings)} amostras",
        "embedding_dim": int(mean_embedding.shape[0]),
        "user_id": user_id
    }


@tool(
    description="Verifica se áudio corresponde ao usuário enrolado.",
    category=ToolCategory.SECURITY,
)
def voice_verify(user_id: str = "master", audio_data: str = None, threshold: float = 0.82) -> dict:
    """
    Verifica voz. Passe audio_data (base64) ou grave ao vivo.

    Args:
        user_id: Usuário a verificar
        audio_data: Base64 do áudio WAV (opcional - se não, grava 3s ao vivo)
        threshold: Similaridade mínima (padrão 0.82, ajuste 0.75-0.9)
    """
    if not RESMBLYZER_AVAILABLE:
        return {"success": False, "message": "Dependências não instaladas"}

    # Carrega voiceprint salvo
    vp_data = _load_voiceprint(user_id)
    if not vp_data:
        return {"success": False, "message": f"Voiceprint não encontrado para '{user_id}'. Rode voice_enroll primeiro."}

    stored_emb = np.array(vp_data["embedding"])

    # Obtém áudio
    if audio_data:
        # Decodifica base64
        import base64, io
        import soundfile as sf
        wav_bytes = base64.b64decode(audio_data)
        audio, sr = sf.read(io.BytesIO(wav_bytes))
        if audio.ndim > 1:
            audio = audio.mean(axis=1)
        if sr != SAMPLE_RATE:
            import librosa
            audio = librosa.resample(audio, orig_sr=sr, target_sr=SAMPLE_RATE)
    else:
        # Grava ao vivo
        try:
            import sounddevice as sd
        except ImportError:
            return {"success": False, "message": "sounddevice necessário para gravação ao vivo"}

        print(f"🎙️  Verificação de voz - fale agora (3s)...")
        recording = sd.rec(int(3 * SAMPLE_RATE), samplerate=SAMPLE_RATE, channels=1, dtype='float32')
        sd.wait()
        audio = recording.flatten()

    # Processa
    audio = _vad_filter(audio)

    if len(audio) < SAMPLE_RATE * 0.5:
        return {"success": False, "message": "Áudio muito curto ou silencioso", "match": False, "score": 0.0}

    test_emb = _compute_embedding(audio)
    score = _compare_embeddings(stored_emb, test_emb)
    match = score >= threshold

    return {
        "success": True,
        "match": bool(match),
        "score": round(float(score), 4),
        "threshold": threshold,
        "user_id": user_id,
        "message": "Voz autenticada ✅" if match else f"Voz NÃO reconhecida (score: {score:.3f})"
    }


@tool(
    description="Lista voiceprints salvos.",
    category=ToolCategory.SECURITY,
)
def voice_list_prints() -> dict:
    """Mostra todos usuários com voiceprint salvo."""
    prints = []
    for f in VOICEPRINT_DIR.glob("*.json"):
        try:
            data = json.loads(f.read_text())
            prints.append({
                "user_id_hash": data.get("user_id_hash"),
                "created_at": data.get("created_at"),
                "updated_at": data.get("updated_at"),
                "samples": data.get("metadata", {}).get("samples"),
                "device": data.get("metadata", {}).get("device"),
            })
        except Exception:
            continue
    return {"success": True, "count": len(prints), "voiceprints": prints}


@tool(
    description="Remove voiceprint de um usuário.",
    category=ToolCategory.SECURITY,
    dangerous=True,
    confirmation_message="Remover voiceprint? Usuário não poderá mais autenticar por voz."
)
def voice_delete_print(user_id: str = "master") -> dict:
    """Deleta voiceprint salvo."""
    path = _voiceprint_path(user_id)
    if path.exists():
        path.unlink()
        return {"success": True, "message": f"Voiceprint de '{user_id}' removido"}
    return {"success": False, "message": f"Voiceprint não encontrado para '{user_id}'"}


@tool(
    description="Testa qualidade do microfone e VAD.",
    category=ToolCategory.SECURITY,
)
def voice_test_mic(duration: float = 3.0) -> dict:
    """Grava e mostra nível de áudio / VAD detection."""
    try:
        import sounddevice as sd
    except ImportError:
        return {"success": False, "message": "sounddevice necessário"}

    print(f"🎙️  Teste de microfone ({duration}s)... fale algo")
    recording = sd.rec(int(duration * SAMPLE_RATE), samplerate=SAMPLE_RATE, channels=1, dtype='float32')
    sd.wait()
    audio = recording.flatten()

    rms = np.sqrt(np.mean(audio**2))
    peak = np.max(np.abs(audio))

    # VAD stats
    voiced = 0
    total = 0
    for i in range(0, len(audio), FRAME_SIZE):
        frame = audio[i:i + FRAME_SIZE]
        if len(frame) < FRAME_SIZE:
            frame = np.pad(frame, (0, FRAME_SIZE - len(frame)))
        frame_int16 = (frame * 32767).astype(np.int16).tobytes()
        if VAD and VAD.is_speech(frame_int16, SAMPLE_RATE):
            voiced += 1
        total += 1

    return {
        "success": True,
        "rms": float(rms),
        "peak": float(peak),
        "voiced_frames": voiced,
        "total_frames": total,
        "voice_ratio": round(voiced / total if total else 0, 2),
        "message": f"RMS: {rms:.4f}, Peak: {peak:.4f}, Voz: {voiced}/{total} frames"
    }


# Export para router
AVAILABLE_FUNCTIONS = {
    "voice_enroll": voice_enroll,
    "voice_verify": voice_verify,
    "voice_list_prints": voice_list_prints,
    "voice_delete_print": voice_delete_print,
    "voice_test_mic": voice_test_mic,
}

DANGEROUS = {"voice_delete_print"}