import sys
import threading
import os
from datetime import datetime
import logging

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QTextEdit, QLineEdit, QPushButton, QLabel, QFrame
)
from PySide6.QtCore import Qt, QThread, Signal, Slot
from PySide6.QtGui import QFont, QColor, QPalette

# Import engine API (public surface)
from jarvis.engine import (
    _load_memory,
    _save_memory,
    _build_prefix_messages,
    _select_tools,
    _run_tool_loop,
    _run_simple_chat_streaming,
    _prune_messages,
    _build_tool_groups,
    DEFAULT_MEMORY_PATH,
    MAX_CONTEXT_MESSAGES,
    MEMORY_UPDATE_EVERY,
    MODEL,
    console,
    SYSTEM_PROMPT,
)

# Tool registry (no `import *`)
from jarvis.tools_registry import get_all_tools

log = logging.getLogger("jarvis.gui")

class JarvisWorker(QThread):
    response_ready = Signal(str, str) # source ("Bot", "System"), text
    thinking_state = Signal(bool)

    def __init__(self, user_text, messages, memory, available_tools, tool_groups, tool_map, opts):
        super().__init__()
        self.user_text = user_text
        self.messages = messages # reference to the exact array
        self.memory = memory
        self.available_tools = available_tools
        self.tool_groups = tool_groups
        self.tool_map = tool_map
        self.opts = opts

    def run(self):
        import asyncio
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        self.thinking_state.emit(True)
        try:
            # Seleccionar tools (reduce contexto)
            active_tools = _select_tools(self.user_text, self.available_tools, self.tool_groups)
            
            # Simple heuristic
            is_simple = False
            s = self.user_text.lower()
            if not any(k in s for k in ["busca", "crea", "ejecuta", "borra", "abre", "cierra", "clima", "weather", "traduce", "archivo", "carpeta"]):
                if len(self.user_text.split()) < 8:
                    is_simple = True # Probably conversational

            # Tool Loop
            if is_simple:
                reply_content = _run_simple_chat_streaming(self.messages, self.opts)
            else:
                reply_content = _run_tool_loop(self.messages, active_tools, self.tool_map, self.opts)
            
            # Formateamos para el history y para hablar. As voices are currently defined in voice.py.
            # Intentaremos emitir el texto para que la GUI lo pronuncie o pinte
            self.response_ready.emit("J.A.R.V.I.S.", reply_content)

        except Exception as e:
            import traceback
            tb = traceback.format_exc()
            log.exception("Worker exception")
            self.response_ready.emit("System", f"Ошибка: {e}\n{tb}")
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
        self.setStyleSheet("""
            QWidget {
                background-color: #121212;
                color: #FFFFFF;
                font-family: 'Segoe UI', Arial, sans-serif;
            }
            QTextEdit {
                background-color: #1E1E1E;
                border: 1px solid #333333;
                border-radius: 8px;
                padding: 10px;
                font-size: 14px;
                line-height: 1.5;
            }
            QLineEdit {
                background-color: #1E1E1E;
                border: 1px solid #005F87;
                border-radius: 8px;
                padding: 10px;
                font-size: 14px;
            }
            QPushButton {
                background-color: #005F87;
                border: none;
                border-radius: 8px;
                padding: 10px 20px;
                font-size: 14px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #0087AF;
            }
            QPushButton:disabled {
                background-color: #333333;
                color: #777777;
            }
            #statusLabel {
                color: #00AFFF;
                font-weight: bold;
                font-size: 12px;
            }
        """)

        # Main Layout
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        layout = QVBoxLayout(central_widget)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(15)

        # Header Profile
        header = QLabel("J.A.R.V.I.S. Systems Online")
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
        log.info("Loading tools...")
        self.available_tools = get_all_tools()
        log.info("Building tool groups...")
        self.tool_groups = _build_tool_groups(self.available_tools)
        self.tool_map = {f.__name__: f for f in self.available_tools}
        
        log.info("Loading memory...")
        self.memory = _load_memory(DEFAULT_MEMORY_PATH)
        log.info("Building messages...")
        self.messages = _build_prefix_messages(self.memory)
        self.opts = {"temperature": 0.3} # Puede overridarse

        self.append_chat("System", "Initializado. A la espera de órdenes.")

    def append_chat(self, sender, text):
        if sender == "You":
            color = "#00FF7F" # Verde
        elif sender == "J.A.R.V.I.S.":
            color = "#00AFFF" # Azul claro
        else:
            color = "#FF4500" # Rojo Naranja
        
        timestamp = datetime.now().strftime("%H:%M:%S")
        html = f"<div style='margin-bottom: 10px;'><b><span style='color: {color};'>{sender}</span></b> ({timestamp})<br>{text.replace(chr(10), '<br>')}</div>"
        
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
        
        # Prepare messages
        self.messages.append({"role": "user", "content": text})

        self.input_field.setEnabled(False)
        self.send_button.setEnabled(False)

        # Launch Worker
        self.worker = JarvisWorker(
            text, self.messages, self.memory, 
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
        self.messages[:] = _prune_messages(self.messages, keep_last=MAX_CONTEXT_MESSAGES)

        # TTS (Optional but cool)
        try:
            from voice import _get_speaker
            speaker = _get_speaker()
            if speaker:
                speaker.speak_async(text)
        except Exception as e:
            log.warning("Voice error: %s", e)

    @Slot(bool)
    def on_thinking(self, is_thinking):
        if is_thinking:
            self.status_label.setText("Status: <span style='color: red;'>Processing (Ollama Local Inference)...</span>")
        else:
            self.status_label.setText("Status: <span style='color: #00FF7F;'>Nominal</span>")
            self.input_field.setEnabled(True)
            self.send_button.setEnabled(True)
            self.input_field.setFocus()

if __name__ == "__main__":
    from jarvis.logging import configure_logging

    configure_logging()
    log.info("GUI start")
    app = QApplication(sys.argv)
    log.debug("QApplication created")
    window = JarvisGUI()
    log.debug("Window created")
    window.show()
    window.raise_()
    window.activateWindow()
    log.info("Window shown, starting event loop...")
    sys.exit(app.exec())
