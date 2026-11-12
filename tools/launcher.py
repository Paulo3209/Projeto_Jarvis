"""
Ferramentas de "reflexo" do J.A.R.V.I.S.: abrir qualquer app instalado, sites,
fechar janelas, controlar mídia/volume e mostrar a área de trabalho.

- launch_app: procura no Menu Iniciar (Get-StartApps) qualquer app instalado,
  inclusive da Microsoft Store, por nome aproximado ("spotify", "vs code",
  "configurações", "explorador de arquivos").
- media_control: teclas multimídia do Windows (funciona com Spotify, YouTube etc.).
"""
from __future__ import annotations

import ctypes
import difflib
import json
import re
import subprocess
import time
import unicodedata
import webbrowser

from core.plugin_system import tool, ToolCategory

_APPS_CACHE: dict = {"t": 0.0, "apps": []}

# Apelidos em português -> nome/ação
ALIASES = {
    "configuracoes": "ms-settings:",
    "configuracao": "ms-settings:",
    "definicoes": "ms-settings:",
    "explorador de arquivos": "explorer.exe",
    "explorador": "explorer.exe",
    "meus arquivos": "explorer.exe",
    "gerenciador de tarefas": "taskmgr.exe",
    "terminal": "wt.exe",
    "prompt de comando": "cmd.exe",
    "cmd": "cmd.exe",
    "powershell": "powershell.exe",
    "bloco de notas": "notepad.exe",
    "calculadora": "calc.exe",
    "paint": "mspaint.exe",
    "vs code": "visual studio code",
    "vscode": "visual studio code",
    "code": "visual studio code",
    "word": "word",
    "excel": "excel",
}

SITES = {
    "youtube": "https://www.youtube.com",
    "google": "https://www.google.com",
    "gmail": "https://mail.google.com",
    "netflix": "https://www.netflix.com",
    "instagram": "https://www.instagram.com",
    "facebook": "https://www.facebook.com",
    "twitter": "https://x.com",
    "github": "https://github.com",
    "chatgpt": "https://chatgpt.com",
    "whatsapp web": "https://web.whatsapp.com",
    "linkedin": "https://www.linkedin.com",
    "mercado livre": "https://www.mercadolivre.com.br",
    "amazon": "https://www.amazon.com.br",
    "maps": "https://maps.google.com",
    "google maps": "https://maps.google.com",
    "tradutor": "https://translate.google.com",
}


def _norm(text: str) -> str:
    text = unicodedata.normalize("NFD", text.lower())
    text = "".join(c for c in text if unicodedata.category(c) != "Mn")
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 .+]", " ", text)).strip()


def _start_apps() -> list[dict]:
    """Apps do Menu Iniciar (cache de 10 min)."""
    if time.time() - _APPS_CACHE["t"] < 600 and _APPS_CACHE["apps"]:
        return _APPS_CACHE["apps"]
    try:
        out = subprocess.run(
            ["powershell.exe", "-NoProfile", "-Command",
             "[Console]::OutputEncoding=[Text.Encoding]::UTF8; Get-StartApps | ConvertTo-Json -Compress"],
            capture_output=True, text=True, encoding="utf-8", timeout=20,
        ).stdout
        apps = json.loads(out) if out.strip() else []
        if isinstance(apps, dict):
            apps = [apps]
        _APPS_CACHE.update(t=time.time(), apps=apps)
    except Exception:
        pass
    return _APPS_CACHE["apps"]


def find_app(name: str) -> dict | None:
    """Encontra o app instalado mais parecido com `name`."""
    target = _norm(name)
    apps = _start_apps()
    by_norm = {_norm(a.get("Name", "")): a for a in apps}
    # Ignora desinstaladores, ajudas e leia-mes
    skip = ("uninstall", "desinstal", "ajuda", "help", "readme", "leia-me", "documentation")
    candidates = {k: v for k, v in by_norm.items() if not any(s in k for s in skip)}
    if target in candidates:
        return candidates[target]
    starts = [k for k in candidates if k.startswith(target)]
    if starts:
        return candidates[min(starts, key=len)]
    contains = [k for k in candidates if re.search(rf"\b{re.escape(target)}\b", k)]
    if contains:
        return candidates[min(contains, key=len)]
    close = difflib.get_close_matches(target, list(candidates), n=1, cutoff=0.72)
    return candidates[close[0]] if close else None


@tool(description="Abre qualquer aplicativo instalado pelo nome (ex.: spotify, chrome, vs code, configurações).",
      category=ToolCategory.SYSTEM)
def launch_app(name: str) -> dict:
    key = _norm(name)
    alias = ALIASES.get(key)
    if alias and (alias.endswith(".exe") or alias.endswith(":")):
        subprocess.Popen(["cmd", "/c", "start", "", alias], shell=False)
        return {"success": True, "message": f"{name} aberto."}
    app = find_app(alias or name)
    if not app:
        return {"success": False, "message": f"Não encontrei o aplicativo '{name}' instalado."}
    subprocess.Popen(["explorer.exe", f"shell:AppsFolder\\{app['AppID']}"])
    return {"success": True, "message": f"{app['Name']} aberto.", "app": app["Name"]}


@tool(description="Abre um site pelo nome (youtube, gmail...) ou endereço, ou pesquisa no Google.",
      category=ToolCategory.WEB)
def open_site(target: str) -> dict:
    key = _norm(target).replace("o site do ", "").replace("site do ", "").replace("site ", "").strip()
    if key in SITES:
        url = SITES[key]
    elif re.match(r"^https?://", target.strip()):
        url = target.strip()
    elif re.match(r"^[\w-]+(\.[\w-]+)+(/.*)?$", key.replace(" ", "")):
        url = "https://" + key.replace(" ", "")
    else:
        from urllib.parse import quote_plus
        url = "https://www.google.com/search?q=" + quote_plus(target)
    webbrowser.open(url)
    return {"success": True, "message": f"Abrindo {url}", "url": url}


@tool(description="Fecha as janelas de um aplicativo pelo nome (o app ainda pode pedir para salvar).",
      category=ToolCategory.SYSTEM)
def close_app(name: str) -> dict:
    try:
        import pygetwindow as gw
    except ImportError:
        return {"success": False, "message": "pygetwindow não instalado."}
    target = _norm(name)
    closed = []
    for w in gw.getAllWindows():
        title = w.title or ""
        if title and target in _norm(title):
            try:
                w.close()
                closed.append(title)
            except Exception:
                pass
    if not closed:
        return {"success": False, "message": f"Nenhuma janela de '{name}' aberta."}
    return {"success": True, "message": f"Fechei {len(closed)} janela(s).", "windows": closed[:5]}


_VK = {
    "play_pause": 0xB3, "next": 0xB0, "previous": 0xB1, "stop": 0xB2,
    "volume_up": 0xAF, "volume_down": 0xAE, "mute": 0xAD,
}


def _press_vk(vk: int, times: int = 1) -> None:
    for _ in range(times):
        ctypes.windll.user32.keybd_event(vk, 0, 0, 0)
        ctypes.windll.user32.keybd_event(vk, 0, 2, 0)
        time.sleep(0.02)


@tool(description="Controla mídia e volume do PC: play_pause, next, previous, stop, volume_up, volume_down, mute.",
      category=ToolCategory.SYSTEM)
def media_control(action: str, steps: int = 5) -> dict:
    action = action.strip().lower()
    if action not in _VK:
        return {"success": False, "message": f"Ação inválida. Use: {', '.join(_VK)}"}
    # Cada passo de volume do Windows = 2%
    times = max(1, min(int(steps), 50)) if action.startswith("volume") else 1
    _press_vk(_VK[action], times)
    return {"success": True, "message": f"Mídia: {action}" + (f" x{times}" if times > 1 else "")}


@tool(description="Minimiza todas as janelas e mostra a área de trabalho (alterna).",
      category=ToolCategory.SYSTEM)
def show_desktop() -> dict:
    VK_LWIN, VK_D = 0x5B, 0x44
    u = ctypes.windll.user32
    u.keybd_event(VK_LWIN, 0, 0, 0)
    u.keybd_event(VK_D, 0, 0, 0)
    u.keybd_event(VK_D, 0, 2, 0)
    u.keybd_event(VK_LWIN, 0, 2, 0)
    return {"success": True, "message": "Área de trabalho exibida."}
