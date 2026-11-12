import os
import platform
import subprocess
import webbrowser
from pathlib import Path
from urllib.parse import urlparse
from datetime import datetime
from core.plugin_system import tool, ToolCategory

# Import all tool modules for router compatibility
from tools.startup import (
    get_time_greeting,
    unlock_pc,
    get_startup_greeting,
)
from tools.desktop_control import (
    list_processes,
    kill_process,
    manage_service,
    network_info,
    network_test,
    power_control,
    run_powershell,
    search_files,
    registry_edit,
    hardware_info,
    simulate_input,
    window_control,
)
from tools.android_control import (
    android_devices,
    android_connect_wifi,
    android_disconnect,
    android_list_packages,
    android_open_app,
    android_close_app,
    android_package_manager,
    android_shell,
    android_screencap,
    android_screenrecord,
    android_input,
    android_communication,
    android_file,
    android_system_info,
    android_settings,
    android_notifications,
    termux_exec,
)
from tools.cross_device import (
    cross_device_connect,
    cross_device_send_command,
    cross_device_list,
    cross_device_sync,
    cross_device_heartbeat,
    cross_device_disconnect,
)
from tools.voice_auth import (
    voice_enroll,
    voice_verify,
    voice_list_prints,
    voice_delete_print,
    voice_test_mic,
)
from voice.voice_gate import (
    voice_gate_mode,
    voice_gate_test,
    voice_gate_status,
)

ROOT = Path(__file__).resolve().parents[1]


def _safe_path(path: str = ".") -> Path:
    p = Path(path)
    if not p.is_absolute():
        p = ROOT / p
    p = p.resolve()
    if p != ROOT and ROOT not in p.parents:
        raise ValueError("Caminho fora da pasta do projeto JARVIS.")
    return p


@tool(
    description="Abre o Bloco de Notas.",
    category=ToolCategory.SYSTEM,
)
def open_notepad() -> dict:
    subprocess.Popen(["notepad.exe"])
    return {"success": True, "message": "Bloco de Notas aberto."}


@tool(
    description="Abre a Calculadora.",
    category=ToolCategory.SYSTEM,
)
def open_calculator() -> dict:
    subprocess.Popen(["calc.exe"])
    return {"success": True, "message": "Calculadora aberta."}


@tool(
    description="Abre um site no navegador.",
    category=ToolCategory.WEB,
)
def open_website(url: str) -> dict:
    """Abre um site no navegador padrão.

    Args:
        url: URL do site (deve começar com http:// ou https://)
    """
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        return {"success": False, "message": "Somente URLs HTTP/HTTPS são permitidas."}
    webbrowser.open(url)
    return {"success": True, "message": f"Site aberto: {url}"}


@tool(
    description="Obtém informações do computador.",
    category=ToolCategory.SYSTEM,
)
def get_system_info() -> dict:
    return {
        "success": True,
        "computer": platform.node(),
        "system": platform.system(),
        "version": platform.version(),
        "machine": platform.machine(),
        "processor": platform.processor(),
        "cwd": str(ROOT),
    }


@tool(
    description="Lista arquivos de uma pasta dentro do projeto JARVIS.",
    category=ToolCategory.FILESYSTEM,
)
def list_files(path: str = ".") -> dict:
    p = _safe_path(path)
    if not p.is_dir():
        return {"success": False, "message": "Não é uma pasta."}
    items = []
    for x in sorted(p.iterdir(), key=lambda z: z.name.lower()):
        items.append({"name": x.name, "type": "folder" if x.is_dir() else "file"})
    return {"success": True, "path": str(p.relative_to(ROOT)), "items": items}


@tool(
    description="Lê um arquivo de texto dentro do projeto JARVIS.",
    category=ToolCategory.FILESYSTEM,
)
def read_file(path: str) -> dict:
    p = _safe_path(path)
    if not p.is_file():
        return {"success": False, "message": "Arquivo não encontrado."}
    if p.stat().st_size > 2_000_000:
        return {"success": False, "message": "Arquivo grande demais para leitura direta."}
    return {
        "success": True,
        "path": str(p.relative_to(ROOT)),
        "content": p.read_text(encoding="utf-8", errors="replace"),
    }


@tool(
    description="Cria ou substitui um arquivo de texto. Requer confirmação.",
    category=ToolCategory.FILESYSTEM,
    dangerous=True,
    confirmation_message="JARVIS vai criar/substituir o arquivo. Confirmar?",
)
def write_file(path: str, content: str) -> dict:
    p = _safe_path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
    return {"success": True, "message": f"Arquivo salvo em {p.relative_to(ROOT)}."}


@tool(
    description="Apaga um arquivo. Requer confirmação.",
    category=ToolCategory.FILESYSTEM,
    dangerous=True,
    confirmation_message="JARVIS vai apagar o arquivo permanentemente. Confirmar?",
)
def delete_file(path: str) -> dict:
    p = _safe_path(path)
    if not p.exists() or not p.is_file():
        return {"success": False, "message": "Arquivo não encontrado."}
    p.unlink()
    return {"success": True, "message": f"Arquivo apagado: {p.relative_to(ROOT)}"}


@tool(
    description="Retorna a data e hora locais.",
    category=ToolCategory.SYSTEM,
)
def get_time() -> dict:
    return {"success": True, "datetime": datetime.now().isoformat(timespec="seconds")}


@tool(
    description="Abre um aplicativo permitido: notepad, calculator ou paint.",
    category=ToolCategory.SYSTEM,
)
def open_app(app: str) -> dict:
    """Abre um aplicativo do Windows.

    Args:
        app: Nome do app (notepad, calculator, paint)
    """
    allowed = {
        "notepad": "notepad.exe",
        "calculator": "calc.exe",
        "paint": "mspaint.exe",
    }
    exe = allowed.get(app.lower())
    if not exe:
        return {"success": False, "message": "Aplicativo não autorizado."}
    subprocess.Popen([exe])
    return {"success": True, "message": f"{app} aberto."}


# Export for backward compatibility
AVAILABLE_FUNCTIONS = {
    # Core system
    "open_notepad": open_notepad,
    "open_calculator": open_calculator,
    "open_website": open_website,
    "get_system_info": get_system_info,
    "list_files": list_files,
    "read_file": read_file,
    "write_file": write_file,
    "delete_file": delete_file,
    "get_time": get_time,
    "open_app": open_app,
    # Startup tools
    "get_time_greeting": get_time_greeting,
    "unlock_pc": unlock_pc,
    "get_startup_greeting": get_startup_greeting,
    # Desktop Control (Admin Master)
    "list_processes": list_processes,
    "kill_process": kill_process,
    "manage_service": manage_service,
    "network_info": network_info,
    "network_test": network_test,
    "power_control": power_control,
    "run_powershell": run_powershell,
    "search_files": search_files,
    "registry_edit": registry_edit,
    "hardware_info": hardware_info,
    "simulate_input": simulate_input,
    "window_control": window_control,
    # Android Control (ADB)
    "android_devices": android_devices,
    "android_connect_wifi": android_connect_wifi,
    "android_disconnect": android_disconnect,
    "android_list_packages": android_list_packages,
    "android_open_app": android_open_app,
    "android_close_app": android_close_app,
    "android_package_manager": android_package_manager,
    "android_shell": android_shell,
    "android_screencap": android_screencap,
    "android_screenrecord": android_screenrecord,
    "android_input": android_input,
    "android_communication": android_communication,
    "android_file": android_file,
    "android_system_info": android_system_info,
    "android_settings": android_settings,
    "android_notifications": android_notifications,
    "termux_exec": termux_exec,
    # Cross-Device (MQTT)
    "cross_device_connect": cross_device_connect,
    "cross_device_send_command": cross_device_send_command,
    "cross_device_list": cross_device_list,
    "cross_device_sync": cross_device_sync,
    "cross_device_heartbeat": cross_device_heartbeat,
    "cross_device_disconnect": cross_device_disconnect,
    # Voice Auth (Speaker Recognition)
    "voice_enroll": voice_enroll,
    "voice_verify": voice_verify,
    "voice_list_prints": voice_list_prints,
    "voice_delete_print": voice_delete_print,
    "voice_test_mic": voice_test_mic,
    # Voice Gate (Access Control)
    "voice_gate_mode": voice_gate_mode,
    "voice_gate_test": voice_gate_test,
    "voice_gate_status": voice_gate_status,
}

DANGEROUS = {
    "delete_file", "write_file",
    "kill_process", "power_control", "run_powershell", "registry_edit",
    "android_package_manager", "android_shell", "android_communication",
    "voice_delete_print",
}