"""
J.A.R.V.I.S. Overlay - interface holográfica que aparece ao ativar o JARVIS.

Roda em processo separado (não trava a voz). Recebe comandos JSON por stdin,
um por linha:
    {"state": "listening", "text": "Sim, senhor?"}
    {"state": "thinking"}  {"state": "speaking", "text": "..."}
    {"state": "user", "text": "abra o chrome"}       # legenda do que você disse
    {"state": "idle"}      # some com fade-out
    {"state": "quit"}

Teste manual:  python -m gui.jarvis_overlay --demo
"""
from __future__ import annotations

import json
import math
import sys
import threading
import time

from PyQt6.QtCore import QObject, QPointF, QRectF, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen, QRadialGradient, QGuiApplication
from PyQt6.QtWidgets import QApplication, QWidget

CYAN = QColor(0, 220, 255)
GOLD = QColor(255, 190, 70)
RED = QColor(255, 80, 80)

STATE_STYLE = {
    "listening": ("OUVINDO", CYAN, 1.0),
    "user": ("OUVINDO", CYAN, 1.0),
    "thinking": ("PROCESSANDO", GOLD, 2.4),
    "speaking": ("RESPONDENDO", CYAN, 1.6),
    "confirm": ("AGUARDANDO CONFIRMAÇÃO", RED, 1.2),
    "online": ("ONLINE", CYAN, 0.8),
}


class StdinReader(QObject):
    message = pyqtSignal(dict)

    def start(self):
        threading.Thread(target=self._run, daemon=True).start()

    def _run(self):
        for line in sys.stdin:
            line = line.strip()
            if not line:
                continue
            try:
                self.message.emit(json.loads(line))
            except json.JSONDecodeError:
                continue
        self.message.emit({"state": "quit"})


class JarvisOverlay(QWidget):
    W, H = 460, 560

    def __init__(self):
        super().__init__()
        self.setWindowTitle("J.A.R.V.I.S.")
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.resize(self.W, self.H)
        screen = QGuiApplication.primaryScreen().availableGeometry()
        self.move(screen.right() - self.W - 30, screen.bottom() - self.H - 30)

        self.state = "online"
        self.caption = ""
        self.user_text = ""
        self.t0 = time.time()
        self.opacity = 0.0
        self.target_opacity = 0.0
        self.level = 0.0  # "volume" simulado para animação da fala

        self.timer = QTimer(self)
        self.timer.timeout.connect(self._tick)
        self.timer.start(16)

    # ---------- Controle ----------
    def handle(self, msg: dict):
        state = msg.get("state", "")
        text = msg.get("text")
        if state == "quit":
            QApplication.quit()
            return
        if state == "idle":
            self.target_opacity = 0.0
            return
        if state == "user":
            self.user_text = text or ""
            self.state = "listening"
        else:
            self.state = state if state in STATE_STYLE else "online"
            if text is not None:
                self.caption = text
            if state in ("listening", "thinking") and text is None:
                self.caption = ""
        if not self.isVisible():
            self.user_text = self.user_text if state == "user" else ""
            self.show()
        self.target_opacity = 1.0

    def _tick(self):
        self.opacity += (self.target_opacity - self.opacity) * 0.12
        if self.target_opacity == 0.0 and self.opacity < 0.02:
            self.opacity = 0.0
            if self.isVisible():
                self.hide()
        self.setWindowOpacity(max(0.0, min(1.0, self.opacity)))
        if self.state == "speaking":
            t = time.time()
            self.level = 0.5 + 0.5 * abs(math.sin(t * 9) * math.sin(t * 3.7 + 1))
        else:
            self.level *= 0.9
        if self.isVisible():
            self.update()

    # ---------- Desenho ----------
    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        label, color, speed = STATE_STYLE.get(self.state, STATE_STYLE["online"])
        t = (time.time() - self.t0) * speed

        # Painel de fundo
        panel = QPainterPath()
        panel.addRoundedRect(QRectF(8, 8, self.W - 16, self.H - 16), 22, 22)
        p.fillPath(panel, QColor(2, 12, 24, 215))
        p.setPen(QPen(QColor(color.red(), color.green(), color.blue(), 120), 1.5))
        p.drawPath(panel)

        cx, cy, R = self.W / 2, 200, 120

        # Brilho do núcleo
        glow = QRadialGradient(QPointF(cx, cy), R * 1.2)
        a = int(90 + 80 * self.level)
        glow.setColorAt(0.0, QColor(color.red(), color.green(), color.blue(), a))
        glow.setColorAt(0.5, QColor(color.red(), color.green(), color.blue(), 25))
        glow.setColorAt(1.0, QColor(0, 0, 0, 0))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(glow)
        p.drawEllipse(QPointF(cx, cy), R * 1.2, R * 1.2)

        # Anéis girando (arcos segmentados)
        rings = [
            (R, 3, 1.0, 6, 40),
            (R * 0.82, 2, -1.6, 4, 70),
            (R * 0.64, 4, 2.3, 3, 90),
            (R * 1.08, 1, -0.6, 24, 8),
        ]
        for radius, width, spd, segs, span in rings:
            pen = QPen(color, width)
            pen.setCapStyle(Qt.PenCapStyle.FlatCap)
            p.setPen(pen)
            p.setBrush(Qt.BrushStyle.NoBrush)
            rect = QRectF(cx - radius, cy - radius, 2 * radius, 2 * radius)
            base = (t * 40 * spd) % 360
            for i in range(segs):
                start = base + i * (360 / segs)
                p.drawArc(rect, int(start * 16), int(span * 16))

        # Marcas de escala
        p.setPen(QPen(QColor(color.red(), color.green(), color.blue(), 110), 1))
        for i in range(60):
            ang = math.radians(i * 6 + t * 5)
            r1, r2 = R * 1.17, R * (1.22 if i % 5 == 0 else 1.19)
            p.drawLine(QPointF(cx + r1 * math.cos(ang), cy + r1 * math.sin(ang)),
                       QPointF(cx + r2 * math.cos(ang), cy + r2 * math.sin(ang)))

        # Núcleo pulsante
        pulse = 0.5 + 0.5 * math.sin(t * 3)
        core_r = R * (0.30 + 0.05 * pulse + 0.10 * self.level)
        core = QRadialGradient(QPointF(cx, cy), core_r)
        core.setColorAt(0.0, QColor(255, 255, 255, 240))
        core.setColorAt(0.45, QColor(color.red(), color.green(), color.blue(), 230))
        core.setColorAt(1.0, QColor(color.red(), color.green(), color.blue(), 0))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(core)
        p.drawEllipse(QPointF(cx, cy), core_r, core_r)

        # Barras de áudio quando fala
        if self.state == "speaking":
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(color.red(), color.green(), color.blue(), 200))
            n = 21
            for i in range(n):
                h = 4 + 26 * self.level * abs(math.sin(i * 0.8 + t * 7))
                x = cx - n * 5 + i * 10
                p.drawRoundedRect(QRectF(x, 345 - h / 2, 5, h), 2, 2)

        # Títulos
        p.setPen(color)
        p.setFont(QFont("Consolas", 18, QFont.Weight.Bold))
        p.drawText(QRectF(0, 22, self.W, 30), Qt.AlignmentFlag.AlignHCenter, "J.A.R.V.I.S.")
        p.setFont(QFont("Consolas", 10))
        p.setPen(QColor(color.red(), color.green(), color.blue(), 200))
        dots = "." * (int(time.time() * 2) % 4) if self.state == "thinking" else ""
        p.drawText(QRectF(0, 372, self.W, 20), Qt.AlignmentFlag.AlignHCenter, f"[ {label}{dots} ]")

        # Legendas
        flags = Qt.AlignmentFlag.AlignHCenter | Qt.TextFlag.TextWordWrap
        if self.user_text:
            p.setPen(QColor(170, 190, 210))
            p.setFont(QFont("Segoe UI", 10))
            p.drawText(QRectF(30, 398, self.W - 60, 40), flags, f"“{self.user_text}”")
        if self.caption:
            p.setPen(QColor(225, 250, 255))
            p.setFont(QFont("Segoe UI", 12))
            p.drawText(QRectF(30, 440, self.W - 60, 100), flags, self.caption[:260])

        p.end()


def main():
    app = QApplication(sys.argv)
    w = JarvisOverlay()

    if "--demo" in sys.argv:
        seq = [
            (0, {"state": "listening", "text": "Sim, senhor?"}),
            (2000, {"state": "user", "text": "qual o status do sistema?"}),
            (3000, {"state": "thinking"}),
            (5000, {"state": "speaking", "text": "Todos os sistemas operacionais, senhor. Processador a doze por cento."}),
            (9000, {"state": "idle"}),
            (11000, {"state": "quit"}),
        ]
        for ms, msg in seq:
            QTimer.singleShot(ms, lambda m=msg: w.handle(m))
    else:
        reader = StdinReader()
        reader.message.connect(w.handle)
        reader.start()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
