"""
JARVIS HUD - PyQt6 Overlay Interface
Always-on-top, transparent, frameless HUD with system metrics, activity log, and text/voice input.
"""
from __future__ import annotations
import asyncio
import sys
import os
from datetime import datetime
from typing import Optional

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QLineEdit, QTextEdit, QPushButton, QProgressBar,
    QFrame, QSizePolicy, QGraphicsDropShadowEffect
)
from PyQt6.QtCore import (
    Qt, QTimer, QThread, pyqtSignal, QPropertyAnimation, QEasingCurve,
    QRect, QPoint, QSize, QEventLoop
)
from PyQt6.QtGui import (
    QFont, QColor, QPalette, QPixmap, QPainter, QLinearGradient,
    QBrush, QPen, QIcon, QTextCursor
)

import psutil


class SystemMetricsThread(QThread):
    """Background thread for system metrics collection."""
    metrics_updated = pyqtSignal(dict)

    def __init__(self, interval: int = 1000):
        super().__init__()
        self.interval = interval
        self._running = True

    def run(self):
        while self._running:
            try:
                cpu_percent = psutil.cpu_percent(interval=0.1)
                memory = psutil.virtual_memory()
                disk = psutil.disk_usage('/')
                net_io = psutil.net_io_counters()

                metrics = {
                    'cpu_percent': cpu_percent,
                    'memory_percent': memory.percent,
                    'memory_used_gb': memory.used / (1024**3),
                    'memory_total_gb': memory.total / (1024**3),
                    'disk_percent': disk.percent,
                    'net_sent_mb': net_io.bytes_sent / (1024**2),
                    'net_recv_mb': net_io.bytes_recv / (1024**2),
                    'timestamp': datetime.now().strftime('%H:%M:%S'),
                }
                self.metrics_updated.emit(metrics)
            except Exception:
                pass
            self.msleep(self.interval)

    def stop(self):
        self._running = False
        self.wait()


class AnimatedProgressBar(QProgressBar):
    """Custom animated progress bar with neon glow effect."""

    def __init__(self, color: str = "#00ffff", parent=None):
        super().__init__(parent)
        self.setRange(0, 100)
        self.setTextVisible(False)
        self.setFixedHeight(8)
        self._color = color
        self._glow_animation = QPropertyAnimation(self, b"value")
        self._glow_animation.setDuration(500)
        self._glow_animation.setEasingCurve(QEasingCurve.Type.OutCubic)

        self.setStyleSheet(f"""
            QProgressBar {{
                border: none;
                border-radius: 4px;
                background-color: rgba(0, 20, 40, 0.8);
            }}
            QProgressBar::chunk {{
                border-radius: 4px;
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 {color}, stop:1 {color}88);
            }}
        """)


class MetricWidget(QWidget):
    """Individual metric display widget (CPU, RAM, etc.)."""

    def __init__(self, label: str, unit: str = "%", color: str = "#00ffff", parent=None):
        super().__init__(parent)
        self.color = color
        self.unit = unit

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(4)

        # Label
        self.label = QLabel(label)
        self.label.setFont(QFont("Consolas", 9))
        self.label.setStyleSheet(f"color: {color}; background: transparent;")
        layout.addWidget(self.label)

        # Value + Progress
        value_layout = QHBoxLayout()
        value_layout.setSpacing(8)

        self.value_label = QLabel("0" + unit)
        self.value_label.setFont(QFont("Consolas", 14, QFont.Weight.Bold))
        self.value_label.setStyleSheet(f"color: {color}; background: transparent;")
        self.value_label.setMinimumWidth(50)
        value_layout.addWidget(self.value_label)

        self.progress = AnimatedProgressBar(color)
        value_layout.addWidget(self.progress, 1)

        layout.addLayout(value_layout)

    def update_value(self, value: float):
        """Update the metric value."""
        self.value_label.setText(f"{value:.1f}{self.unit}")
        self.progress.setValue(int(min(max(value, 0), 100)))


class ActivityLogWidget(QWidget):
    """Activity log display with colored entries."""

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(4)

        # Header
        header = QLabel("ACTIVITY LOG")
        header.setFont(QFont("Consolas", 9, QFont.Weight.Bold))
        header.setStyleSheet("color: #00ffff; background: transparent;")
        layout.addWidget(header)

        # Log text area
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setFont(QFont("Consolas", 8))
        self.log_text.setStyleSheet("""
            QTextEdit {
                background-color: rgba(0, 10, 20, 0.9);
                border: 1px solid #004466;
                border-radius: 4px;
                color: #88ffcc;
                padding: 4px;
            }
            QScrollBar:vertical {
                background: rgba(0, 10, 20, 0.5);
                width: 8px;
                border: none;
            }
            QScrollBar::handle:vertical {
                background: #006688;
                border-radius: 4px;
            }
        """)
        self.log_text.setMinimumHeight(150)
        layout.addWidget(self.log_text)

        # Colors for different log types
        self.colors = {
            'info': '#88ffcc',
            'tool': '#00aaff',
            'tool_success': '#00ff88',
            'tool_error': '#ff4444',
            'memory': '#aa88ff',
            'user': '#ffffff',
            'assistant': '#00ffff',
            'system': '#ffaa00',
            'error': '#ff4444',
        }

    def add_entry(self, message: str, entry_type: str = 'info'):
        """Add a log entry with timestamp and color."""
        timestamp = datetime.now().strftime('%H:%M:%S')
        color = self.colors.get(entry_type, '#88ffcc')

        # Move cursor to end and insert formatted text
        cursor = self.log_text.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)

        # Timestamp
        cursor.insertHtml(f'<span style="color:#6688aa;">[{timestamp}] </span>')
        # Message
        cursor.insertHtml(f'<span style="color:{color};">{message}</span><br>')

        # Auto-scroll
        self.log_text.ensureCursorVisible()

        # Limit lines
        doc = self.log_text.document()
        if doc.blockCount() > 100:
            cursor = QTextCursor(doc)
            cursor.movePosition(QTextCursor.MoveOperation.Start)
            cursor.movePosition(QTextCursor.MoveOperation.Down, QTextCursor.MoveMode.KeepAnchor, doc.blockCount() - 80)
            cursor.removeSelectedText()


class InputWidget(QWidget):
    """Text input field with send button."""

    message_submitted = pyqtSignal(str)
    voice_toggled = pyqtSignal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        # Text input
        self.input_field = QLineEdit()
        self.input_field.setPlaceholderText("Digite sua mensagem... (Enter para enviar)")
        self.input_field.setFont(QFont("Consolas", 10))
        self.input_field.setStyleSheet("""
            QLineEdit {
                background-color: rgba(0, 10, 20, 0.9);
                border: 1px solid #004466;
                border-radius: 20px;
                color: #00ffff;
                padding: 8px 16px;
                selection-background-color: #004466;
            }
            QLineEdit:focus {
                border: 1px solid #00ffff;
            }
        """)
        self.input_field.returnPressed.connect(self._on_submit)
        layout.addWidget(self.input_field, 1)

        # Voice button
        self.voice_btn = QPushButton("🎤")
        self.voice_btn.setFixedSize(40, 40)
        self.voice_btn.setCheckable(True)
        self.voice_btn.setToolTip("Ativar entrada de voz")
        self.voice_btn.setStyleSheet("""
            QPushButton {
                background-color: rgba(0, 20, 40, 0.9);
                border: 1px solid #004466;
                border-radius: 20px;
                color: #00ffff;
                font-size: 16px;
            }
            QPushButton:hover {
                border: 1px solid #00ffff;
                background-color: rgba(0, 40, 80, 0.9);
            }
            QPushButton:checked {
                background-color: rgba(255, 50, 50, 0.3);
                border: 1px solid #ff4444;
                color: #ff6666;
            }
            QPushButton:checked:hover {
                background-color: rgba(255, 80, 80, 0.4);
            }
        """)
        self.voice_btn.toggled.connect(self.voice_toggled.emit)
        layout.addWidget(self.voice_btn)

        # Send button
        self.send_btn = QPushButton("▶")
        self.send_btn.setFixedSize(40, 40)
        self.send_btn.setToolTip("Enviar (Enter)")
        self.send_btn.setStyleSheet("""
            QPushButton {
                background-color: rgba(0, 60, 100, 0.9);
                border: 1px solid #006688;
                border-radius: 20px;
                color: #00ffff;
                font-size: 16px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: rgba(0, 100, 160, 0.9);
                border: 1px solid #00ffff;
            }
            QPushButton:pressed {
                background-color: rgba(0, 140, 200, 0.9);
            }
        """)
        self.send_btn.clicked.connect(self._on_submit)
        layout.addWidget(self.send_btn)

    def _on_submit(self):
        text = self.input_field.text().strip()
        if text:
            self.message_submitted.emit(text)
            self.input_field.clear()

    def set_enabled(self, enabled: bool):
        self.input_field.setEnabled(enabled)
        self.send_btn.setEnabled(enabled)
        self.voice_btn.setEnabled(enabled)

    def clear(self):
        self.input_field.clear()


class StatusIndicator(QWidget):
    """Status indicator with pulsing animation."""

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 4, 8, 4)
        layout.setSpacing(8)

        self.dot = QLabel("●")
        self.dot.setFont(QFont("Consolas", 12))
        self.dot.setStyleSheet("color: #00ff88; background: transparent;")
        layout.addWidget(self.dot)

        self.label = QLabel("ONLINE")
        self.label.setFont(QFont("Consolas", 10, QFont.Weight.Bold))
        self.label.setStyleSheet("color: #00ff88; background: transparent;")
        layout.addWidget(self.label)

        layout.addStretch()

        # Pulsing animation
        self._animation = QPropertyAnimation(self.dot, b"styleSheet")
        self._animation.setDuration(1000)
        self._animation.setLoopCount(-1)
        self._animation.setKeyValueAt(0, "color: #00ff88; background: transparent;")
        self._animation.setKeyValueAt(0.5, "color: #008844; background: transparent;")
        self._animation.setKeyValueAt(1, "color: #00ff88; background: transparent;")
        self._animation.start()

    def set_status(self, status: str, color: str = "#00ff88"):
        """Update status text and color."""
        self.label.setText(status.upper())
        self.label.setStyleSheet(f"color: {color}; background: transparent;")
        self.dot.setStyleSheet(f"color: {color}; background: transparent;")

        # Update animation colors
        dark_color = self._darken_color(color)
        self._animation.setKeyValueAt(0, f"color: {color}; background: transparent;")
        self._animation.setKeyValueAt(0.5, f"color: {dark_color}; background: transparent;")
        self._animation.setKeyValueAt(1, f"color: {color}; background: transparent;")

    def _darken_color(self, hex_color: str) -> str:
        """Darken a hex color for pulse animation."""
        hex_color = hex_color.lstrip('#')
        r = int(hex_color[0:2], 16)
        g = int(hex_color[2:4], 16)
        b = int(hex_color[4:6], 16)
        r = max(0, r // 2)
        g = max(0, g // 2)
        b = max(0, b // 2)
        return f"#{r:02x}{g:02x}{b:02x}"


class HUDWindow(QMainWindow):
    """Main HUD overlay window."""

    # Signals for communication with async backend
    send_message = pyqtSignal(str)
    toggle_voice = pyqtSignal(bool)
    shutdown_requested = pyqtSignal()

    def __init__(self):
        super().__init__()
        self._setup_window()
        self._setup_ui()
        self._setup_metrics_thread()
        self._apply_theme()

    def _setup_window(self):
        """Configure window properties for overlay."""
        self.setWindowTitle("JARVIS HUD")
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.Tool |
            Qt.WindowType.NoDropShadowWindowHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)

        # Position at top-right of screen
        screen = QApplication.primaryScreen().geometry()
        self.setGeometry(screen.width() - 420, 0, 400, screen.height())

        # Enable dragging
        self._drag_pos = None

    def _setup_ui(self):
        """Setup the main UI layout."""
        central = QWidget()
        self.setCentralWidget(central)

        # Main layout with background frame
        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(0, 0, 0, 0)

        # Background frame with rounded corners and glow
        self.bg_frame = QFrame()
        self.bg_frame.setObjectName("bgFrame")
        self.bg_frame.setStyleSheet("""
            #bgFrame {
                background-color: rgba(0, 15, 30, 0.95);
                border: 1px solid #003355;
                border-radius: 12px;
            }
        """)

        # Add drop shadow
        shadow = QGraphicsDropShadowEffect()
        shadow.setBlurRadius(30)
        shadow.setColor(QColor(0, 100, 200, 100))
        shadow.setOffset(0, 0)
        self.bg_frame.setGraphicsEffect(shadow)

        layout = QVBoxLayout(self.bg_frame)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Title bar
        self._create_title_bar(layout)

        # Content area
        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(12, 8, 12, 12)
        content_layout.setSpacing(12)

        # Status indicator
        self.status_indicator = StatusIndicator()
        content_layout.addWidget(self.status_indicator)

        # System metrics
        self._create_metrics_section(content_layout)

        # Activity log
        self.activity_log = ActivityLogWidget()
        content_layout.addWidget(self.activity_log, 1)

        # Input area
        self.input_widget = InputWidget()
        self.input_widget.message_submitted.connect(self.send_message.emit)
        self.input_widget.voice_toggled.connect(self.toggle_voice.emit)
        content_layout.addWidget(self.input_widget)

        layout.addWidget(content)
        main_layout.addWidget(self.bg_frame)

    def _create_title_bar(self, layout: QVBoxLayout):
        """Create custom title bar with JARVIS branding."""
        title_bar = QWidget()
        title_bar.setFixedHeight(48)
        title_bar.setStyleSheet("""
            background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                stop:0 rgba(0, 40, 80, 0.9), stop:1 rgba(0, 20, 50, 0.9));
            border-top-left-radius: 12px;
            border-top-right-radius: 12px;
            border-bottom: 1px solid #003355;
        """)

        title_layout = QHBoxLayout(title_bar)
        title_layout.setContentsMargins(16, 0, 16, 0)

        # JARVIS logo/name
        self.title_label = QLabel("J.A.R.V.I.S.")
        self.title_label.setFont(QFont("Consolas", 14, QFont.Weight.Bold))
        self.title_label.setStyleSheet("color: #00ffff; background: transparent;")
        title_layout.addWidget(self.title_label)

        # Version badge
        self.version_label = QLabel("LEVEL 5")
        self.version_label.setFont(QFont("Consolas", 8))
        self.version_label.setStyleSheet("""
            color: #0088ff;
            background: rgba(0, 100, 200, 0.3);
            padding: 2px 8px;
            border-radius: 8px;
            border: 1px solid #004488;
        """)
        title_layout.addWidget(self.version_label)

        title_layout.addStretch()

        # Minimize/Close buttons
        self.minimize_btn = QPushButton("—")
        self.minimize_btn.setFixedSize(28, 28)
        self.minimize_btn.setStyleSheet(self._button_style("#006688"))
        self.minimize_btn.clicked.connect(self.showMinimized)
        title_layout.addWidget(self.minimize_btn)

        self.close_btn = QPushButton("✕")
        self.close_btn.setFixedSize(28, 28)
        self.close_btn.setStyleSheet(self._button_style("#880000", hover="#cc0000"))
        self.close_btn.clicked.connect(self._on_close)
        title_layout.addWidget(self.close_btn)

        layout.addWidget(title_bar)

    def _button_style(self, base_color: str, hover: str = None) -> str:
        hover_color = hover or base_color
        return f"""
            QPushButton {{
                background-color: {base_color};
                border: none;
                border-radius: 14px;
                color: white;
                font-size: 12px;
                font-weight: bold;
            }}
            QPushButton:hover {{
                background-color: {hover_color};
            }}
        """

    def _create_metrics_section(self, layout: QVBoxLayout):
        """Create system metrics widgets."""
        metrics_frame = QFrame()
        metrics_frame.setStyleSheet("""
            background-color: rgba(0, 20, 40, 0.6);
            border: 1px solid #002244;
            border-radius: 8px;
        """)

        metrics_layout = QVBoxLayout(metrics_frame)
        metrics_layout.setContentsMargins(12, 10, 12, 10)
        metrics_layout.setSpacing(8)

        # Header
        header = QLabel("SYSTEM METRICS")
        header.setFont(QFont("Consolas", 9, QFont.Weight.Bold))
        header.setStyleSheet("color: #00ffff; background: transparent;")
        metrics_layout.addWidget(header)

        # Metrics grid
        grid = QHBoxLayout()
        grid.setSpacing(12)

        self.cpu_widget = MetricWidget("CPU", "%", "#00ff88")
        self.ram_widget = MetricWidget("RAM", "%", "#00aaff")
        self.disk_widget = MetricWidget("DISK", "%", "#ffaa00")

        grid.addWidget(self.cpu_widget, 1)
        grid.addWidget(self.ram_widget, 1)
        grid.addWidget(self.disk_widget, 1)

        metrics_layout.addLayout(grid)
        layout.addWidget(metrics_frame)

    def _setup_metrics_thread(self):
        """Start system metrics collection thread."""
        self.metrics_thread = SystemMetricsThread(interval=2000)
        self.metrics_thread.metrics_updated.connect(self._on_metrics_update)
        self.metrics_thread.start()

    def _on_metrics_update(self, metrics: dict):
        """Update metric widgets with new data."""
        self.cpu_widget.update_value(metrics['cpu_percent'])
        self.ram_widget.update_value(metrics['memory_percent'])
        self.disk_widget.update_value(metrics['disk_percent'])

        # Log significant changes
        if metrics['cpu_percent'] > 80:
            self.activity_log.add_entry(f"CPU alto: {metrics['cpu_percent']:.1f}%", 'warning')
        if metrics['memory_percent'] > 85:
            self.activity_log.add_entry(f"RAM alto: {metrics['memory_percent']:.1f}%", 'warning')

    def _apply_theme(self):
        """Apply global theme."""
        self.setStyleSheet("""
            QMainWindow {
                background: transparent;
            }
            QWidget {
                font-family: Consolas, monospace;
            }
        """)

    def _on_close(self):
        """Handle close button."""
        self.shutdown_requested.emit()
        self.close()

    # Event handlers for window dragging
    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_pos = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()

    def mouseMoveEvent(self, event):
        if event.buttons() == Qt.MouseButton.LeftButton and self._drag_pos:
            self.move(event.globalPosition().toPoint() - self._drag_pos)
            event.accept()

    def mouseReleaseEvent(self, event):
        self._drag_pos = None
        event.accept()

    # Public methods for external control
    def set_status(self, status: str, color: str = "#00ff88"):
        """Update status indicator."""
        self.status_indicator.set_status(status, color)

    def log_activity(self, message: str, entry_type: str = 'info'):
        """Add entry to activity log."""
        self.activity_log.add_entry(message, entry_type)

    def log_user_message(self, message: str):
        """Log user message."""
        self.activity_log.add_entry(f"Você: {message}", 'user')

    def log_assistant_token(self, token: str):
        """Log assistant token (append to last assistant entry)."""
        # For streaming, we'll handle this specially
        pass

    def log_assistant_response(self, response: str):
        """Log complete assistant response."""
        self.activity_log.add_entry(f"JARVIS: {response[:100]}{'...' if len(response) > 100 else ''}", 'assistant')

    def log_tool_call(self, tool_name: str, args: dict):
        """Log tool invocation."""
        args_str = ", ".join(f"{k}={v}" for k, v in args.items())[:60]
        self.activity_log.add_entry(f"🔧 {tool_name}({args_str})", 'tool')

    def log_tool_result(self, tool_name: str, success: bool, message: str = ""):
        """Log tool result."""
        if success:
            self.activity_log.add_entry(f"✓ {tool_name}: {message[:60]}", 'tool_success')
        else:
            self.activity_log.add_entry(f"✗ {tool_name}: {message[:60]}", 'tool_error')

    def log_memory(self, action: str, content: str):
        """Log memory operation."""
        self.activity_log.add_entry(f"💾 {action}: {content[:60]}", 'memory')

    def log_error(self, error: str):
        """Log error."""
        self.activity_log.add_entry(f"⚠ {error}", 'error')

    def set_input_enabled(self, enabled: bool):
        """Enable/disable input."""
        self.input_widget.set_enabled(enabled)

    def append_streaming_token(self, token: str):
        """Append token to streaming response in log."""
        # Get the last block and append
        cursor = self.activity_log.log_text.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)

        # Check if last entry is assistant streaming
        # For simplicity, just append to log
        self.activity_log.log_text.insertPlainText(token)
        self.activity_log.log_text.ensureCursorVisible()

    def closeEvent(self, event):
        """Clean up on close."""
        self.metrics_thread.stop()
        self.shutdown_requested.emit()
        super().closeEvent(event)


def create_hud_app() -> tuple[QApplication, HUDWindow]:
    """Create and return QApplication and HUD window."""
    # Enable high DPI scaling
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )

    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)

    app.setStyle('Fusion')

    # Dark palette
    palette = QPalette()
    palette.setColor(QPalette.ColorRole.Window, QColor(0, 15, 30))
    palette.setColor(QPalette.ColorRole.WindowText, QColor(0, 255, 255))
    palette.setColor(QPalette.ColorRole.Base, QColor(0, 10, 20))
    palette.setColor(QPalette.ColorRole.AlternateBase, QColor(0, 20, 40))
    palette.setColor(QPalette.ColorRole.ToolTipBase, QColor(0, 30, 60))
    palette.setColor(QPalette.ColorRole.ToolTipText, QColor(0, 255, 255))
    palette.setColor(QPalette.ColorRole.Text, QColor(0, 255, 255))
    palette.setColor(QPalette.ColorRole.Button, QColor(0, 30, 60))
    palette.setColor(QPalette.ColorRole.ButtonText, QColor(0, 255, 255))
    palette.setColor(QPalette.ColorRole.BrightText, QColor(255, 0, 0))
    palette.setColor(QPalette.ColorRole.Highlight, QColor(0, 100, 200))
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor(0, 0, 0))
    app.setPalette(palette)

    hud = HUDWindow()
    hud.show()

    return app, hud


if __name__ == "__main__":
    app, hud = create_hud_app()
    sys.exit(app.exec())