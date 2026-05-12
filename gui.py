import sys
import os
from datetime import datetime
import logging
import html as html_module

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QTextEdit, QLineEdit, QPushButton, QLabel, QFrame
)
from PySide6.QtCore import Qt, QThread, Signal, Slot
from PySide6.QtGui import QFont, QColor, QPalette

# Import engine public API (no underscore prefix)
from jarvis.engine import (
    select_tools,
    run_tool_loop,
    run_simple_chat,
    prune_messages,
    build_tool_groups,
    MAX_CONTEXT_MESSAGES,
    MODEL,
    SYSTEM_PROMPT,
)

# Tool registry
from jarvis.tools_registry import get_all_tools

# Brain (Obsidian vault)
from brain import JarvisBrain

log = logging.getLogger("jarvis.gui")

_APP_QSS = """
    QWidget {
        background-color: #0f1117;
        color: #e8e8e8;
        font-family: 'Segoe UI', Arial, sans-serif;
        font-size: 13px;
    }
    QTextEdit {
        background-color: #121826;
        border: 1px solid rgba(255, 255, 255, 0.08);
        border-radius: 12px;
        padding: 12px;
        font-size: 13px;
        line-height: 1.55;
        selection-background-color: #2d4b72;
    }
    QLineEdit {
        background-color: #0f1623;
        border: 1px solid rgba(255, 255, 255, 0.10);
        border-radius: 12px;
        padding: 10px 12px;
        font-size: 13px;
    }
    QLineEdit:focus {
        border: 1px solid #4cc9f0;
    }
    QPushButton {
        background-color: #2563eb;
        border: 1px solid rgba(255, 255, 255, 0.12);
        border-radius: 12px;
        padding: 10px 16px;
        font-size: 13px;
        font-weight: 600;
    }
    QPushButton:hover {
        background-color: #3b82f6;
    }
    QPushButton:pressed {
        background-color: #1d4ed8;
    }
    QPushButton:disabled {
        background-color: rgba(255, 255, 255, 0.08);
        color: rgba(255, 255, 255, 0.45);
        border: 1px solid rgba(255, 255, 255, 0.08);
    }
    QLabel#headerLabel {
        color: #e8e8e8;
        font-size: 18px;
        font-weight: 700;
        letter-spacing: 0.5px;
        padding: 6px 0;
    }
    QLabel#statusLabel {
        color: rgba(232, 232, 232, 0.85);
        font-size: 12px;
    }
    QScrollBar:vertical {
        border: none;
        background: transparent;
        width: 10px;
        margin: 6px 2px 6px 2px;
    }
    QScrollBar::handle:vertical {
        background: rgba(255, 255, 255, 0.18);
        border-radius: 5px;
        min-height: 24px;
    }
    QScrollBar::handle:vertical:hover {
        background: rgba(255, 255, 255, 0.28);
    }
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
        height: 0px;
    }
    QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {
        background: transparent;
    }
"""

class JarvisWorker(QThread):
    response_ready = Signal(str, str) # source ("Bot", "System"), text
    thinking_state = Signal(bool)

    def __init__(self, user_text, messages, available_tools, tool_groups, tool_map, opts):
        super().__init__()
        self.user_text = user_text
        self.messages = messages # reference to the exact array
        self.available_tools = available_tools
        self.tool_groups = tool_groups
        self.tool_map = tool_map
        self.opts = opts

    def run(self):
        self.thinking_state.emit(True)
        try:
            # Seleccionar tools (reduce contexto)
            active_tools = select_tools(self.user_text, self.available_tools, self.tool_groups)
            
            # Simple heuristic
            is_simple = False
            s = self.user_text.lower()
            if not any(k in s for k in ["busca", "crea", "ejecuta", "borra", "abre", "cierra", "clima", "weather", "traduce", "archivo", "carpeta"]):
                if len(self.user_text.split()) < 8:
                    is_simple = True # Probably conversational

            # Tool Loop
            if is_simple:
                reply_content = run_simple_chat(self.messages, self.opts)
            else:
                reply_content = run_tool_loop(self.messages, active_tools, self.tool_map, self.opts)
            
            self.response_ready.emit("J.A.R.V.I.S.", reply_content)

        except Exception as e:
            import traceback
            tb = traceback.format_exc()
            log.exception("Worker exception")
            self.response_ready.emit("System", f"Error: {e}\n{tb}")
        finally:
            self.thinking_state.emit(False)


class JarvisGUI(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("J.A.R.V.I.S. Control Panel")
        self.resize(850, 700)
        
        # Centrar en pantalla
        try:
            screen = QApplication.primaryScreen().geometry()
            x = (screen.width() - 850) // 2
            y = (screen.height() - 700) // 2
            self.move(x, y)
        except Exception as e:
            print("No se pudo centrar:", e)
        self.setStyleSheet(_APP_QSS)

        # Main Layout
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        layout = QVBoxLayout(central_widget)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(15)

        # Header Profile
        header = QLabel("J.A.R.V.I.S. Systems Online")
        header.setObjectName("headerLabel")
        header.setFont(QFont('Segoe UI', 18, QFont.Bold))
        header.setAlignment(Qt.AlignCenter)
        layout.addWidget(header)

        # Conversation History
        self.chat_display = QTextEdit()
        self.chat_display.setReadOnly(True)
        layout.addWidget(self.chat_display, stretch=1)

        # Status Indicator
        self.status_label = QLabel("Status: Idle")
        self.status_label.setObjectName("statusLabel")
        layout.addWidget(self.status_label)

        # Input Area
        input_layout = QHBoxLayout()
        self.input_field = QLineEdit()
        self.input_field.setPlaceholderText("Comanda a J.A.R.V.I.S. aquí... (Ej: abre youtube)")
        self.input_field.returnPressed.connect(self.handle_send)
        input_layout.addWidget(self.input_field)

        self.send_button = QPushButton("Transmitir")
        self.send_button.clicked.connect(self.handle_send)
        input_layout.addWidget(self.send_button)

        layout.addLayout(input_layout)

        log.info("Init JARVIS GUI...")
        self.init_jarvis()
        log.info("JARVIS initialized.")
        self.worker = None

    def init_jarvis(self):
        # Brain (Obsidian vault)
        log.info("Initializing brain...")
        self.brain = JarvisBrain()
        self.brain.initialize()

        log.info("Loading tools...")
        self.available_tools = get_all_tools()
        log.info("Building tool groups...")
        self.tool_groups = build_tool_groups(self.available_tools)
        self.tool_map = {f.__name__: f for f in self.available_tools}
        
        log.info("Building messages...")
        self.messages = [{"role": "system", "content": SYSTEM_PROMPT}]
        self.opts = {"temperature": 0.3}

        self.append_chat("System", "Inicializado. A la espera de órdenes.")

    def append_chat(self, sender, text):
        timestamp = datetime.now().strftime("%H:%M:%S")
        safe_sender = html_module.escape(sender)
        safe_text = html_module.escape(text).replace("\n", "<br>")

        if sender == "You":
            bubble_bg = "#143c2a"
            border = "rgba(34, 197, 94, 0.25)"
            align = "right"
            name_color = "#22c55e"
        elif sender == "J.A.R.V.I.S.":
            bubble_bg = "#132a44"
            border = "rgba(76, 201, 240, 0.20)"
            align = "left"
            name_color = "#4cc9f0"
        else:
            bubble_bg = "#3a1f1f"
            border = "rgba(239, 68, 68, 0.25)"
            align = "left"
            name_color = "#f87171"

        html = (
            f"<div style='margin: 10px 0; text-align: {align};'>"
            f"<div style='display: inline-block; max-width: 78%; background: {bubble_bg};"
            f" border: 1px solid {border}; border-radius: 14px; padding: 10px 12px;'>"
            f"<div style='font-size: 11px; opacity: 0.85; margin-bottom: 6px;'>"
            f"<span style='color: {name_color}; font-weight: 700;'>{safe_sender}</span>"
            f"<span style='opacity: 0.65;'> · {timestamp}</span>"
            f"</div>"
            f"<div style='font-size: 13px; line-height: 1.55;'>{safe_text}</div>"
            f"</div>"
            f"</div>"
        )

        self.chat_display.append(html)
        # Scroll to bottom
        scrollbar = self.chat_display.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

    @Slot()
    def handle_send(self):
        text = self.input_field.text().strip()
        if not text:
            return
        
        self.input_field.clear()
        self.append_chat("You", text)
        
        # Inyectar contexto del vault antes de cada turno
        vault_context = self.brain.before_turn(text)
        if vault_context:
            self.messages.append({"role": "system", "content": vault_context})

        # Prepare messages
        self.messages.append({"role": "user", "content": text})

        self.input_field.setEnabled(False)
        self.send_button.setEnabled(False)

        # Launch Worker
        self.worker = JarvisWorker(
            text, self.messages,
            self.available_tools, self.tool_groups, self.tool_map, self.opts
        )
        self.worker.response_ready.connect(self.on_bot_reply)
        self.worker.thinking_state.connect(self.on_thinking)
        self.worker.start()

    @Slot(str, str)
    def on_bot_reply(self, sender, text):
        self.append_chat(sender, text)
        self.messages.append({"role": "assistant", "content": text})
        
        # Clean context
        self.messages[:] = prune_messages(self.messages, keep_last=MAX_CONTEXT_MESSAGES)

        # Brain: registrar turno y aprender
        user_text = ""
        for m in reversed(self.messages):
            if m.get("role") == "user":
                user_text = m.get("content", "")
                break
        self.brain.after_turn(user_text, text)

        # TTS (Optional but cool)
        try:
            from voice import VoiceSpeaker
            speaker = VoiceSpeaker()
            speaker.speak_async(text)
        except Exception as e:
            log.warning("Voice error: %s", e)

    @Slot(bool)
    def on_thinking(self, is_thinking):
        if is_thinking:
            self.status_label.setText("Status: <span style='color: #f59e0b;'>Procesando (Ollama local)...</span>")
        else:
            self.status_label.setText("Status: <span style='color: #22c55e;'>Nominal</span>")
            self.input_field.setEnabled(True)
            self.send_button.setEnabled(True)
            self.input_field.setFocus()

    def closeEvent(self, event):
        """Shutdown limpio del brain al cerrar la ventana."""
        try:
            self.brain.shutdown("Sesión GUI cerrada")
        except Exception:
            pass
        super().closeEvent(event)

def main() -> None:
    from jarvis.logging import configure_logging

    configure_logging()
    log.info("GUI start")
    app = QApplication(sys.argv)
    window = JarvisGUI()
    window.show()
    window.raise_()
    window.activateWindow()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
