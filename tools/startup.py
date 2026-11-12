"""
Startup tools for JARVIS - Time-based greetings and PC unlock.
"""
import os
import subprocess
import ctypes
from datetime import datetime
from core.plugin_system import tool, ToolCategory


@tool(
    description="Retorna uma saudação baseada na hora do dia (bom dia, boa tarde, boa noite).",
    category=ToolCategory.SYSTEM,
)
def get_time_greeting() -> dict:
    """Retorna saudação apropriada para a hora atual."""
    hour = datetime.now().hour

    if 5 <= hour < 12:
        greeting = "Bom dia"
    elif 12 <= hour < 18:
        greeting = "Boa tarde"
    else:
        greeting = "Boa noite"

    return {
        "success": True,
        "greeting": greeting,
        "hour": hour,
        "message": f"{greeting}! São {hour:02d}:{datetime.now().minute:02d}."
    }


@tool(
    description="Tenta desbloquear/acordar o PC enviando teclas para sair da tela de bloqueio.",
    category=ToolCategory.SYSTEM,
)
def unlock_pc() -> dict:
    """
    Tenta acordar o monitor e enviar Ctrl+Alt+Del para chegar à tela de login.
    NOTA: Não pode burlar a segurança do Windows - ainda exigirá senha/PIN/Windows Hello.
    """
    try:
        # Constantes do Windows
        INPUT_KEYBOARD = 1
        KEYEVENTF_KEYUP = 0x0002
        VK_CONTROL = 0x11
        VK_MENU = 0x12  # Alt
        VK_DELETE = 0x2E

        # Estrutura para SendInput
        class KEYBDINPUT(ctypes.Structure):
            _fields_ = [
                ("wVk", ctypes.c_ushort),
                ("wScan", ctypes.c_ushort),
                ("dwFlags", ctypes.c_ulong),
                ("time", ctypes.c_ulong),
                ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
            ]

        class INPUT(ctypes.Structure):
            _fields_ = [
                ("type", ctypes.c_ulong),
                ("ki", KEYBDINPUT),
            ]

        # Função para enviar tecla
        def send_key(vk, keyup=False):
            flags = KEYEVENTF_KEYUP if keyup else 0
            inp = INPUT(INPUT_KEYBOARD, KEYBDINPUT(vk, 0, flags, 0, None))
            ctypes.windll.user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(inp))

        # Acordar o monitor (envia SC_MONITORPOWER)
        HWND_BROADCAST = 0xFFFF
        WM_SYSCOMMAND = 0x0112
        SC_MONITORPOWER = 0xF170
        ctypes.windll.user32.PostMessageW(HWND_BROADCAST, WM_SYSCOMMAND, SC_MONITORPOWER, -1)

        # Pequena pausa
        import time
        time.sleep(0.5)

        # Enviar Ctrl+Alt+Del (requer privilégios de sistema para funcionar na tela de bloqueio)
        # Nota: Isso pode não funcionar na tela de bloqueio segura do Windows
        send_key(VK_CONTROL)
        send_key(VK_MENU)
        send_key(VK_DELETE)
        time.sleep(0.1)
        send_key(VK_DELETE, keyup=True)
        send_key(VK_MENU, keyup=True)
        send_key(VK_CONTROL, keyup=True)

        return {
            "success": True,
            "message": "Comando de desbloqueio enviado. Se o PC estava bloqueado, a tela de login deve aparecer (ainda exigirá senha/PIN/Windows Hello)."
        }

    except Exception as e:
        return {
            "success": False,
            "message": f"Erro ao tentar desbloquear: {e}"
        }


@tool(
    description="Retorna mensagem de boas-vindas personalizada com saudação por horário.",
    category=ToolCategory.SYSTEM,
)
def get_startup_greeting(user_name: str = "Senhor") -> dict:
    """Gera mensagem de boas-vindas completa para inicialização do JARVIS."""
    hour = datetime.now().hour

    if 5 <= hour < 12:
        period = "manhã"
        greeting = "Bom dia"
    elif 12 <= hour < 18:
        period = "tarde"
        greeting = "Boa tarde"
    else:
        period = "noite"
        greeting = "Boa noite"

    messages = {
        "manhã": [
            f"{greeting}, {user_name}. Tenha uma excelente {period}.",
            f"{greeting}, {user_name}. Sistemas prontos para um novo dia.",
            f"{greeting}. Que sua {period} seja produtiva, {user_name}.",
        ],
        "tarde": [
            f"{greeting}, {user_name}. Como posso ajudar nesta {period}?",
            f"{greeting}, {user_name}. Sistemas operacionais.",
            f"{greeting}. Boa {period}, {user_name}.",
        ],
        "noite": [
            f"{greeting}, {user_name}. Trabalhando tarde hoje?",
            f"{greeting}, {user_name}. Sistemas à disposição.",
            f"{greeting}. Boa {period}, {user_name}.",
        ],
    }

    import random
    message = random.choice(messages[period])

    return {
        "success": True,
        "greeting": greeting,
        "period": period,
        "hour": hour,
        "message": message
    }


# Export for backward compatibility
AVAILABLE_FUNCTIONS = {
    "get_time_greeting": get_time_greeting,
    "unlock_pc": unlock_pc,
    "get_startup_greeting": get_startup_greeting,
}