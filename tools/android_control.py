"""
Controle Android via ADB - Requer ADB instalado e depuração USB ativada no celular.
Para Wi-Fi: adb tcpip 5555 && adb connect IP:5555
"""
import subprocess
import json
import time
import re
from pathlib import Path
from typing import Optional, List, Dict, Any
from core.plugin_system import tool, ToolCategory


# ==================== UTILITÁRIOS ADB ====================

ADB_PATH = "adb"  # Assume no PATH, ou use caminho completo

def _adb(cmd: list, device: str = None, timeout: int = 30) -> dict:
    """Executa comando ADB."""
    full_cmd = [ADB_PATH]
    if device:
        full_cmd.extend(["-s", device])
    full_cmd.extend(cmd)

    try:
        result = subprocess.run(full_cmd, capture_output=True, text=True, timeout=timeout)
        return {
            "success": result.returncode == 0,
            "stdout": result.stdout.strip(),
            "stderr": result.stderr.strip(),
            "returncode": result.returncode
        }
    except subprocess.TimeoutExpired:
        return {"success": False, "error": f"Timeout ({timeout}s)"}
    except FileNotFoundError:
        return {"success": False, "error": "ADB não encontrado. Instale Android SDK Platform Tools e adicione ao PATH."}
    except Exception as e:
        return {"success": False, "error": str(e)}


def _get_devices() -> list:
    """Lista dispositivos conectados."""
    result = _adb(["devices", "-l"])
    if not result["success"]:
        return []

    devices = []
    for line in result["stdout"].split("\n")[1:]:
        if line.strip() and "\tdevice" in line:
            parts = line.split()
            device_id = parts[0]
            props = {}
            for p in parts[1:]:
                if ":" in p:
                    k, v = p.split(":", 1)
                    props[k] = v
            devices.append({"id": device_id, **props})
    return devices


# ==================== DISPOSITIVOS ====================

@tool(description="Lista dispositivos Android conectados via ADB.", category=ToolCategory.SYSTEM)
def android_devices() -> dict:
    """Mostra dispositivos conectados (USB/Wi-Fi)."""
    devices = _get_devices()
    return {"success": True, "count": len(devices), "devices": devices}


@tool(description="Conecta ao Android via Wi-Fi (precisa USB primeiro para ativar tcpip).", category=ToolCategory.SYSTEM)
def android_connect_wifi(ip: str, port: int = 5555) -> dict:
    """Conecta via Wi-Fi: adb connect IP:PORT. Precisa ter feito 'adb tcpip 5555' via USB antes."""
    result = _adb(["connect", f"{ip}:{port}"])
    if result["success"]:
        # Verifica se conectou
        time.sleep(1)
        devices = _get_devices()
        connected = any(d["id"].startswith(f"{ip}:{port}") for d in devices)
        return {"success": connected, "message": result["stdout"] or result["stderr"], "devices": devices}
    return {"success": False, "message": result["stderr"]}


@tool(description="Desconecta dispositivo ADB.", category=ToolCategory.SYSTEM)
def android_disconnect(device: str = None) -> dict:
    """Desconecta device específico ou todos."""
    cmd = ["disconnect"]
    if device:
        cmd.append(device)
    result = _adb(cmd)
    return {"success": result["success"], "message": result["stdout"]}


# ==================== APLICATIVOS ====================

@tool(description="Lista apps instalados no Android.", category=ToolCategory.SYSTEM)
def android_list_packages(device: str = None, filter_name: str = "", system: bool = False, user: bool = True) -> dict:
    """Lista pacotes. system=true para apps de sistema, user=true para apps do usuário."""
    cmd = ["shell", "pm", "list", "packages"]
    if system:
        cmd.append("-s")
    if user:
        cmd.append("-3")  # third party
    if filter_name:
        cmd.append(f"| grep {filter_name}")

    result = _adb(cmd, device)
    if result["success"]:
        packages = []
        for line in result["stdout"].split("\n"):
            if line.startswith("package:"):
                pkg = line.replace("package:", "").strip()
                packages.append(pkg)
        return {"success": True, "count": len(packages), "packages": packages[:100]}
    return {"success": False, "message": result["stderr"]}


@tool(description="Abre app no Android por package name ou activity.", category=ToolCategory.SYSTEM)
def android_open_app(device: str = None, package: str = "", activity: str = "") -> dict:
    """Abre app. Use package (ex: com.whatsapp) ou package/activity."""
    if not package:
        return {"success": False, "message": "Package name obrigatório"}

    if activity:
        cmd = ["shell", "am", "start", "-n", f"{package}/{activity}"]
    else:
        cmd = ["shell", "monkey", "-p", package, "-c", "android.intent.category.LAUNCHER", "1"]

    result = _adb(cmd, device)
    return {"success": result["success"], "message": result["stdout"] or result["stderr"]}


@tool(description="Fecha app no Android.", category=ToolCategory.SYSTEM)
def android_close_app(device: str = None, package: str = "") -> dict:
    """Força parada do app."""
    if not package:
        return {"success": False, "message": "Package name obrigatório"}

    result = _adb(["shell", "am", "force-stop", package], device)
    return {"success": result["success"], "message": result["stdout"] or result["stderr"]}


@tool(description="Instala/Desinstala APK no Android.", category=ToolCategory.SYSTEM, dangerous=True, confirmation_message="Instalar/desinstalar apps no celular. Confirmar?")
def android_package_manager(action: str, device: str = None, package: str = "", apk_path: str = "") -> dict:
    """Ações: install, uninstall, clear_data, grant_permission, revoke_permission."""
    if action == "install":
        if not apk_path:
            return {"success": False, "message": "Caminho do APK obrigatório"}
        result = _adb(["install", "-r", apk_path], device, timeout=120)
    elif action == "uninstall":
        if not package:
            return {"success": False, "message": "Package name obrigatório"}
        result = _adb(["uninstall", package], device)
    elif action == "clear_data":
        if not package:
            return {"success": False, "message": "Package name obrigatório"}
        result = _adb(["shell", "pm", "clear", package], device)
    elif action == "grant_permission":
        if not package or "permission" not in kwargs:
            return {"success": False, "message": "Package e permission obrigatórios"}
        result = _adb(["shell", "pm", "grant", package, kwargs["permission"]], device)
    elif action == "revoke_permission":
        if not package or "permission" not in kwargs:
            return {"success": False, "message": "Package e permission obrigatórios"}
        result = _adb(["shell", "pm", "revoke", package, kwargs["permission"]], device)
    else:
        return {"success": False, "message": "Ações: install, uninstall, clear_data, grant_permission, revoke_permission"}

    return {"success": result["success"], "message": result["stdout"] or result["stderr"]}


# ==================== SHELL E COMANDOS ====================

@tool(description="Executa comando shell no Android.", category=ToolCategory.SYSTEM, dangerous=True, confirmation_message="Executar comando shell arbitrário no Android. CUIDADO: acesso root pode brickar o dispositivo.")
def android_shell(device: str = None, command: str = "", as_root: bool = False) -> dict:
    """Executa comando shell. as_root=true tenta su (precisa root)."""
    if not command:
        return {"success": False, "message": "Comando obrigatório"}

    if as_root:
        cmd = ["shell", "su", "-c", command]
    else:
        cmd = ["shell", command]

    result = _adb(cmd, device, timeout=60)
    return {"success": result["success"], "stdout": result["stdout"][:5000], "stderr": result["stderr"][:2000]}


@tool(description="Captura tela do Android e salva no PC.", category=ToolCategory.SYSTEM)
def android_screencap(device: str = None, save_path: str = "android_screen.png") -> dict:
    """Captura screenshot do celular."""
    # Captura no device
    result = _adb(["shell", "screencap", "-p", "/sdcard/screen.png"], device)
    if not result["success"]:
        return {"success": False, "message": result["stderr"]}

    # Puxa para o PC
    result = _adb(["pull", "/sdcard/screen.png", save_path], device)
    if result["success"]:
        # Limpa no device
        _adb(["shell", "rm", "/sdcard/screen.png"], device)
        return {"success": True, "message": f"Screenshot salvo em {save_path}"}
    return {"success": False, "message": result["stderr"]}


@tool(description="Grava tela do Android (máx 3 min).", category=ToolCategory.SYSTEM)
def android_screenrecord(device: str = None, save_path: str = "android_record.mp4", duration: int = 30) -> dict:
    """Grava tela. duration em segundos (máx 180)."""
    if duration > 180:
        duration = 180

    remote_path = "/sdcard/record.mp4"
    # Grava em background
    result = _adb(["shell", "screenrecord", "--time-limit", str(duration), remote_path], device, timeout=duration + 10)

    if result["success"]:
        # Puxa arquivo
        pull_result = _adb(["pull", remote_path, save_path], device, timeout=30)
        _adb(["shell", "rm", remote_path], device)
        if pull_result["success"]:
            return {"success": True, "message": f"Vídeo salvo em {save_path}"}
        return {"success": False, "message": pull_result["stderr"]}
    return {"success": False, "message": result["stderr"]}


# ==================== INPUT E AUTOMAÇÃO ====================

@tool(description="Simula toque/toque longo/swipe no Android.", category=ToolCategory.SYSTEM)
def android_input(device: str = None, action: str = "tap", x: int = 0, y: int = 0, x2: int = None, y2: int = None, duration: int = 300) -> dict:
    """Ações: tap, swipe, long_press, text, keyevent."""
    if action == "tap":
        cmd = ["shell", "input", "tap", str(x), str(y)]
    elif action == "swipe":
        if x2 is None or y2 is None:
            return {"success": False, "message": "Swipe requer x2, y2"}
        cmd = ["shell", "input", "swipe", str(x), str(y), str(x2), str(y2), str(duration)]
    elif action == "long_press":
        cmd = ["shell", "input", "swipe", str(x), str(y), str(x), str(y), "1000"]
    elif action == "text":
        text = kwargs.get("text", "")
        # Escapa espaços e caracteres especiais
        escaped = text.replace(" ", "%s").replace("'", "\\'").replace('"', '\\"')
        cmd = ["shell", "input", "text", escaped]
    elif action == "keyevent":
        key = kwargs.get("keycode", "KEYCODE_HOME")
        cmd = ["shell", "input", "keyevent", key]
    else:
        return {"success": False, "message": "Ações: tap, swipe, long_press, text, keyevent"}

    result = _adb(cmd, device)
    return {"success": result["success"], "message": result["stdout"] or result["stderr"]}


@tool(description="Envia SMS ou faz ligação no Android.", category=ToolCategory.SYSTEM, dangerous=True, confirmation_message="Enviar SMS ou fazer ligação. Confirmar?")
def android_communication(device: str = None, action: str = "sms", number: str = "", message: str = "") -> dict:
    """Ações: sms, call. Para SMS precisa permissão SEND_SMS."""
    if action == "sms":
        if not number or not message:
            return {"success": False, "message": "Número e mensagem obrigatórios"}
        # Usa intent para abrir app de SMS (não envia direto sem permissão especial)
        cmd = ["shell", "am", "start", "-a", "android.intent.action.SENDTO", "-d", f"sms:{number}", "--es", "sms_body", message]
    elif action == "call":
        if not number:
            return {"success": False, "message": "Número obrigatório"}
        cmd = ["shell", "am", "start", "-a", "android.intent.action.CALL", "-d", f"tel:{number}"]
    else:
        return {"success": False, "message": "Ações: sms, call"}

    result = _adb(cmd, device)
    return {"success": result["success"], "message": result["stdout"] or result["stderr"]}


# ==================== ARQUIVOS ====================

@tool(description="Gerencia arquivos no Android (push, pull, list, delete, mkdir).", category=ToolCategory.SYSTEM)
def android_file(device: str = None, action: str = "list", remote_path: str = "/sdcard/", local_path: str = "") -> dict:
    """Ações: push (PC->Android), pull (Android->PC), list, delete, mkdir, stat."""
    if action == "push":
        if not local_path:
            return {"success": False, "message": "local_path obrigatório para push"}
        result = _adb(["push", local_path, remote_path], device, timeout=60)
    elif action == "pull":
        if not local_path:
            return {"success": False, "message": "local_path obrigatório para pull"}
        result = _adb(["pull", remote_path, local_path], device, timeout=60)
    elif action == "list":
        result = _adb(["shell", "ls", "-la", remote_path], device)
    elif action == "delete":
        result = _adb(["shell", "rm", "-rf", remote_path], device)
    elif action == "mkdir":
        result = _adb(["shell", "mkdir", "-p", remote_path], device)
    elif action == "stat":
        result = _adb(["shell", "stat", remote_path], device)
    else:
        return {"success": False, "message": "Ações: push, pull, list, delete, mkdir, stat"}

    return {"success": result["success"], "message": result["stdout"] or result["stderr"]}


# ==================== SISTEMA E INFO ====================

@tool(description="Informações do sistema Android (bateria, armazenamento, versão, sensores).", category=ToolCategory.SYSTEM)
def android_system_info(device: str = None) -> dict:
    """Info completa do dispositivo."""
    info = {}

    # Propriedades do sistema
    props = _adb(["shell", "getprop"], device)
    if props["success"]:
        prop_dict = {}
        for line in props["stdout"].split("\n"):
            match = re.match(r'\[(.*?)\]: \[(.*?)\]', line)
            if match:
                prop_dict[match.group(1)] = match.group(2)
        info["properties"] = {
            "model": prop_dict.get("ro.product.model"),
            "brand": prop_dict.get("ro.product.brand"),
            "device": prop_dict.get("ro.product.device"),
            "android_version": prop_dict.get("ro.build.version.release"),
            "sdk": prop_dict.get("ro.build.version.sdk"),
            "security_patch": prop_dict.get("ro.build.version.security_patch"),
            "fingerprint": prop_dict.get("ro.build.fingerprint"),
            "root": prop_dict.get("ro.secure") == "0",
        }

    # Bateria
    battery = _adb(["shell", "dumpsys", "battery"], device)
    if battery["success"]:
        bat_info = {}
        for line in battery["stdout"].split("\n"):
            if ":" in line:
                k, v = line.split(":", 1)
                bat_info[k.strip()] = v.strip()
        info["battery"] = bat_info

    # Armazenamento
    storage = _adb(["shell", "df", "/data"], device)
    if storage["success"]:
        info["storage"] = storage["stdout"]

    # Memória
    mem = _adb(["shell", "cat", "/proc/meminfo"], device)
    if mem["success"]:
        info["memory"] = mem["stdout"][:1000]

    # CPU
    cpu = _adb(["shell", "cat", "/proc/cpuinfo"], device)
    if cpu["success"]:
        info["cpu"] = cpu["stdout"][:1000]

    return {"success": True, "device": device or "default", "info": info}


@tool(description="Controla configurações do Android (Wi-Fi, Bluetooth, GPS, brilho, volume, modo avião).", category=ToolCategory.SYSTEM)
def android_settings(device: str = None, setting: str = "", value: str = "") -> dict:
    """Configurações: wifi, bluetooth, gps, airplane, brightness, volume, rotation, mobile_data."""
    settings_map = {
        "wifi": ("wifi", "1" if value.lower() in ["on", "true", "1"] else "0"),
        "bluetooth": ("bluetooth", "1" if value.lower() in ["on", "true", "1"] else "0"),
        "gps": ("location", "1" if value.lower() in ["on", "true", "1"] else "0"),
        "airplane": ("airplane_mode_on", "1" if value.lower() in ["on", "true", "1"] else "0"),
        "brightness": ("screen_brightness", value),  # 0-255
        "volume": ("volume_music", value),  # 0-15
        "rotation": ("accelerometer_rotation", "1" if value.lower() in ["on", "true", "1"] else "0"),
        "mobile_data": ("mobile_data", "1" if value.lower() in ["on", "true", "1"] else "0"),
    }

    if setting not in settings_map:
        return {"success": False, "message": f"Configurações: {', '.join(settings_map.keys())}"}

    namespace, val = settings_map[setting]

    if setting in ["wifi", "bluetooth", "gps", "airplane", "mobile_data"]:
        # Usa service call ou settings put
        if setting == "wifi":
            cmd = ["shell", "svc", "wifi", "enable" if val == "1" else "disable"]
        elif setting == "bluetooth":
            cmd = ["shell", "service", "call", "bluetooth_manager", "8"] if val == "1" else ["shell", "service", "call", "bluetooth_manager", "9"]
        elif setting == "gps":
            cmd = ["shell", "settings", "put", "secure", "location_providers_allowed", "+gps" if val == "1" else "-gps"]
        elif setting == "airplane":
            cmd = ["shell", "settings", "put", "global", "airplane_mode_on", val]
            _adb(["shell", "am", "broadcast", "-a", "android.intent.action.AIRPLANE_MODE", "--ez", "state", val], device)
        elif setting == "mobile_data":
            cmd = ["shell", "svc", "data", "enable" if val == "1" else "disable"]
    else:
        cmd = ["shell", "settings", "put", "system" if setting in ["brightness", "rotation"] else "global", namespace, val]

    result = _adb(cmd, device)
    return {"success": result["success"], "message": result["stdout"] or result["stderr"]}


# ==================== NOTIFICAÇÕES ====================

@tool(description="Lê notificações do Android (precisa permissão de notificação).", category=ToolCategory.SYSTEM)
def android_notifications(device: str = None, action: str = "list", package: str = "") -> dict:
    """Ações: list, clear, clear_all. Precisa 'Notification Listener' ativado."""
    if action == "list":
        cmd = ["shell", "dumpsys", "notification", "--noredact"]
        if package:
            cmd.append(f"| grep {package}")
    elif action == "clear_all":
        cmd = ["shell", "cmd", "notification", "clear_all"]
    elif action == "clear":
        if not package:
            return {"success": False, "message": "Package obrigatório para clear"}
        cmd = ["shell", "cmd", "notification", "clear", package]
    else:
        return {"success": False, "message": "Ações: list, clear, clear_all"}

    result = _adb(cmd, device)
    if result["success"] and action == "list":
        # Parse básico
        notifications = []
        current = {}
        for line in result["stdout"].split("\n"):
            if "NotificationRecord" in line:
                if current:
                    notifications.append(current)
                current = {"raw": line}
            elif current and ":" in line:
                k, v = line.split(":", 1)
                current[k.strip()] = v.strip()
        if current:
            notifications.append(current)
        return {"success": True, "count": len(notifications), "notifications": notifications[:20]}

    return {"success": result["success"], "message": result["stdout"] or result["stderr"]}


# ==================== TERMUX (Linux no Android) ====================

@tool(description="Executa comandos no Termux (Linux no Android). Requer Termux instalado e 'termux-api'.", category=ToolCategory.SYSTEM)
def termux_exec(device: str = None, command: str = "", package: str = "com.termux") -> dict:
    """Executa comando no Termux via intent."""
    if not command:
        return {"success": False, "message": "Comando obrigatório"}

    # Usa termux:exec intent
    escaped = command.replace(" ", "%20").replace("'", "%27").replace('"', "%22")
    uri = f"termux:exec?cmd={escaped}"
    cmd = ["shell", "am", "start", "-a", "android.intent.action.VIEW", "-d", uri, package]
    result = _adb(cmd, device)
    return {"success": result["success"], "message": result["stdout"] or result["stderr"]}


# ==================== EXPORT ====================

AVAILABLE_FUNCTIONS = {
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
}

DANGEROUS = {"android_package_manager", "android_shell", "android_communication"}