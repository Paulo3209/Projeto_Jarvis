"""
Cliente do overlay holográfico: inicia `gui/jarvis_overlay.py` em outro processo
e envia mudanças de estado. Se PyQt6/tela não estiverem disponíveis, vira no-op.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Optional

PROJECT_ROOT = Path(__file__).resolve().parents[1]


class OverlayClient:
    def __init__(self, enabled: bool = True):
        self.enabled = enabled
        self._proc: Optional[subprocess.Popen] = None

    def start(self) -> bool:
        if not self.enabled:
            return False
        try:
            self._proc = subprocess.Popen(
                [sys.executable, "-m", "gui.jarvis_overlay"],
                cwd=str(PROJECT_ROOT),
                stdin=subprocess.PIPE,
                text=True,
                encoding="utf-8",
            )
            return True
        except Exception as e:
            print(f"[Overlay] Não foi possível iniciar a interface visual: {e}")
            self._proc = None
            return False

    def send(self, state: str, text: Optional[str] = None) -> None:
        if not self._proc or self._proc.poll() is not None or not self._proc.stdin:
            return
        msg = {"state": state}
        if text is not None:
            msg["text"] = text
        try:
            self._proc.stdin.write(json.dumps(msg, ensure_ascii=False) + "\n")
            self._proc.stdin.flush()
        except (BrokenPipeError, OSError, ValueError):
            self._proc = None

    # Atalhos
    def listening(self, text: Optional[str] = None): self.send("listening", text)
    def user(self, text: str): self.send("user", text)
    def thinking(self): self.send("thinking")
    def speaking(self, text: str): self.send("speaking", text)
    def confirm(self, text: str): self.send("confirm", text)
    def hide(self): self.send("idle")

    def stop(self) -> None:
        self.send("quit")
        if self._proc:
            try:
                self._proc.wait(timeout=2)
            except Exception:
                self._proc.kill()
            self._proc = None
