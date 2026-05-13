import sys
import os
import shutil
import uuid
import logging
import html as html_module
from datetime import datetime
from pathlib import Path

from PySide6.QtWidgets import (
    QApplication,
    QMainWindow,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QTextEdit,
    QLineEdit,
    QPushButton,
    QLabel,
    QFrame,
    QSizePolicy,
    QFileDialog,
)
from PySide6.QtCore import Qt, QThread, Signal, Slot, QEvent
from PySide6.QtGui import QFont, QFontDatabase, QGuiApplication, QImage, QKeySequence

# Import engine public API (no underscore prefix)
from aaris.engine import (
    select_tools,
    run_tool_loop,
    run_simple_chat,
    prune_messages,
    build_tool_groups,
    MAX_CONTEXT_MESSAGES,
    MODEL,
    refresh_system_prompt,
    SYSTEM_PROMPT,
    _is_simple_conversational,
)

# Tool registry
from aaris.tools_registry import get_all_tools

# Brain (Obsidian vault)
from brain import AarisBrain

log = logging.getLogger("aaris.gui")

# Adjuntos: límite por defecto (sobreescribible con env)
_GUI_MAX_ATTACHMENTS = int(os.environ.get("AARIS_GUI_MAX_ATTACHMENTS", "8"))
_GUI_MAX_ATTACH_BYTES = int(os.environ.get("AARIS_GUI_MAX_ATTACH_BYTES", str(15 * 1024 * 1024)))


def _ollama_options_for_turn(user_text: str) -> dict:
    """
    Opciones Ollama por turno: temperatura baja cuando hay herramientas (mejor tool-calling).
    Overrides: AARIS_GUI_TEMP_TOOLS, AARIS_GUI_TEMP_CHAT, OLLAMA_NUM_CTX, OLLAMA_TEMPERATURE (solo charla).
    """
    opts: dict = {}
    if ctx := os.environ.get("OLLAMA_NUM_CTX"):
        try:
            opts["num_ctx"] = int(ctx)
        except ValueError:
            pass

    plan_mode = os.environ.get("AARIS_PLAN_MODE", "off")
    tools_turn = not (_is_simple_conversational(user_text) and plan_mode == "off")

    def _f(env_key: str, default: str) -> float:
        raw = os.environ.get(env_key, default).strip()
        try:
            return float(raw)
        except ValueError:
            return float(default)

    if tools_turn:
        opts["temperature"] = _f("AARIS_GUI_TEMP_TOOLS", "0.1")
    else:
        chat_t = os.environ.get("AARIS_GUI_TEMP_CHAT", "").strip()
        if chat_t:
            opts["temperature"] = _f("AARIS_GUI_TEMP_CHAT", "0.35")
        else:
            opts["temperature"] = _f("OLLAMA_TEMPERATURE", "0.35")
    return opts


def _sanitize_chat_display_text(text: str) -> str:
    """Evita llenar el chat si el modelo devuelve spam (p. ej. 'sourceMapping' en bucle)."""
    if not text or len(text) < 80:
        return text
    low = text.lower()
    if low.count("sourcemapping") >= 4:
        return (
            "[Respuesta omitida: el modelo generó texto corrupto repetido. "
            "Vuelva a pedir la web o abra el index.html si el archivo ya se creó.]"
        )
    return text


# Paleta: fondo zinc oscuro, acento cian, usuario violeta suave
_APP_QSS = """
    QMainWindow, QWidget#centralRoot {
        background-color: #09090b;
    }
    QWidget {
        color: #f4f4f5;
        font-family: "Segoe UI", "SF Pro Text", system-ui, -apple-system, sans-serif;
        font-size: 14px;
    }
    QFrame#headerBar {
        background-color: #18181b;
        border: none;
        border-bottom: 1px solid rgba(255, 255, 255, 0.06);
        border-radius: 0px;
    }
    QFrame#chatPanel {
        background-color: #0c0c0e;
        border: 1px solid rgba(255, 255, 255, 0.06);
        border-radius: 16px;
    }
    QTextEdit#chatDisplay {
        background-color: transparent;
        border: none;
        border-radius: 12px;
        padding: 8px 4px;
        font-size: 14px;
        line-height: 1.6;
        selection-background-color: #3b82f680;
        selection-color: #fafafa;
    }
    QLineEdit#messageInput {
        background-color: #18181b;
        border: 1px solid rgba(255, 255, 255, 0.10);
        border-radius: 14px;
        padding: 12px 16px;
        font-size: 14px;
        min-height: 22px;
    }
    QLineEdit#messageInput:focus {
        border: 1px solid #22d3ee;
        background-color: #1c1c21;
    }
    QLineEdit#messageInput:disabled {
        color: rgba(244, 244, 245, 0.45);
        background-color: #121214;
    }
    QPushButton#sendButton {
        background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
            stop:0 #0891b2, stop:1 #0e7490);
        border: 1px solid rgba(34, 211, 238, 0.35);
        border-radius: 14px;
        padding: 12px 22px;
        font-size: 14px;
        font-weight: 600;
        color: #f0fdfa;
        min-width: 108px;
    }
    QPushButton#sendButton:hover {
        background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
            stop:0 #06b6d4, stop:1 #0891b2);
        border: 1px solid rgba(34, 211, 238, 0.55);
    }
    QPushButton#sendButton:pressed {
        background: #0e7490;
    }
    QPushButton#sendButton:disabled {
        background: #27272a;
        color: rgba(244, 244, 245, 0.4);
        border: 1px solid rgba(255, 255, 255, 0.06);
    }
    QPushButton#attachBtn {
        background-color: #27272a;
        border: 1px solid rgba(255, 255, 255, 0.12);
        border-radius: 10px;
        padding: 6px 12px;
        font-size: 12px;
        font-weight: 600;
        color: #e4e4e7;
        min-height: 28px;
    }
    QPushButton#attachBtn:hover {
        background-color: #3f3f46;
        border: 1px solid rgba(255, 255, 255, 0.18);
    }
    QLabel#titleLabel {
        color: #fafafa;
        font-size: 22px;
        font-weight: 700;
        letter-spacing: 0.12em;
    }
    QLabel#subtitleLabel {
        color: rgba(244, 244, 245, 0.55);
        font-size: 12px;
        font-weight: 500;
    }
    QLabel#modelBadge {
        color: #a5f3fc;
        font-size: 11px;
        font-weight: 600;
        background-color: rgba(34, 211, 238, 0.12);
        border: 1px solid rgba(34, 211, 238, 0.22);
        border-radius: 8px;
        padding: 4px 10px;
    }
    QLabel#statusLabel {
        color: rgba(244, 244, 245, 0.65);
        font-size: 12px;
        padding: 2px 0;
    }
    QFrame#inputBar {
        background-color: transparent;
        border: none;
    }
    QScrollBar:vertical {
        border: none;
        background: transparent;
        width: 8px;
        margin: 4px 2px 4px 0px;
    }
    QScrollBar::handle:vertical {
        background: rgba(255, 255, 255, 0.14);
        border-radius: 4px;
        min-height: 36px;
    }
    QScrollBar::handle:vertical:hover {
        background: rgba(255, 255, 255, 0.22);
    }
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
        height: 0px;
    }
    QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {
        background: transparent;
    }
"""

_CHAT_DOC_CSS = """
    body {
        margin: 0;
        padding: 12px 16px 24px 16px;
        color: #e4e4e7;
        font-family: "Segoe UI", "SF Pro Text", system-ui, sans-serif;
        font-size: 14px;
        line-height: 1.6;
    }
    a { color: #67e8f9; text-decoration: none; }
    a:hover { text-decoration: underline; }
    code {
        font-family: Consolas, "Cascadia Mono", monospace;
        font-size: 0.9em;
        background: rgba(0, 0, 0, 0.35);
        padding: 2px 7px;
        border-radius: 6px;
        color: #fde68a;
    }
    pre {
        font-family: Consolas, "Cascadia Mono", monospace;
        font-size: 12px;
        background: #09090b;
        color: #e4e4e7;
        padding: 14px 16px;
        border-radius: 12px;
        border: 1px solid rgba(255, 255, 255, 0.08);
        white-space: pre-wrap;
        margin: 10px 0;
    }
"""


class AarisWorker(QThread):
    response_ready = Signal(str, str)
    thinking_state = Signal(bool)

    def __init__(self, user_text, messages, available_tools, tool_groups, tool_map, opts):
        super().__init__()
        self.user_text = user_text
        self.messages = messages
        self.available_tools = available_tools
        self.tool_groups = tool_groups
        self.tool_map = tool_map
        self.opts = opts

    def run(self):
        self.thinking_state.emit(True)
        try:
            active_tools = select_tools(self.user_text, self.available_tools, self.tool_groups)

            plan_mode = os.environ.get("AARIS_PLAN_MODE", "off")
            if _is_simple_conversational(self.user_text) and plan_mode == "off":
                reply_content = run_simple_chat(self.messages, self.opts)
            else:
                reply_content = run_tool_loop(self.messages, active_tools, self.tool_map, self.opts)

            self.response_ready.emit("A.A.R.I.S.", reply_content)

        except Exception as e:
            import traceback

            tb = traceback.format_exc()
            log.exception("Worker exception")
            self.response_ready.emit("System", f"Error: {e}\n{tb}")
        finally:
            self.thinking_state.emit(False)


class AarisGUI(QMainWindow):
    def __init__(self):
        super().__init__()
        self._attachments: list[dict] = []
        self.setWindowTitle("A.A.R.I.S.")
        self.setMinimumSize(880, 640)
        self.resize(960, 760)

        try:
            screen = QApplication.primaryScreen().geometry()
            g = self.frameGeometry()
            g.moveCenter(screen.center())
            self.move(g.topLeft())
        except Exception as e:
            print("No se pudo centrar:", e)

        self.setStyleSheet(_APP_QSS)

        central = QWidget()
        central.setObjectName("centralRoot")
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # —— Cabecera ——
        header = QFrame()
        header.setObjectName("headerBar")
        header.setFixedHeight(88)
        hb = QHBoxLayout(header)
        hb.setContentsMargins(28, 16, 28, 16)
        hb.setSpacing(16)

        title_col = QVBoxLayout()
        title_col.setSpacing(4)
        title = QLabel("A.A.R.I.S.")
        title.setObjectName("titleLabel")
        sub = QLabel("Asistente local · adjunta imágenes/PDF · visión multimodal (AARIS_VISION_MODEL)")
        sub.setObjectName("subtitleLabel")
        title_col.addWidget(title)
        title_col.addWidget(sub)
        title_col.addStretch()
        hb.addLayout(title_col, stretch=1)

        badge = QLabel(MODEL)
        badge.setObjectName("modelBadge")
        badge.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        hb.addWidget(badge, alignment=Qt.AlignTop)

        self.btn_open_projects = QPushButton("Abrir Proyectos")
        self.btn_open_projects.setObjectName("attachBtn")
        self.btn_open_projects.setCursor(Qt.PointingHandCursor)
        self.btn_open_projects.setToolTip("Abre la carpeta por defecto para código (Documentos/Proyectos)")
        self.btn_open_projects.clicked.connect(self._open_default_projects_folder)
        hb.addWidget(self.btn_open_projects, alignment=Qt.AlignTop)

        root.addWidget(header)

        # —— Cuerpo: panel de chat ——
        body = QWidget()
        body_l = QVBoxLayout(body)
        body_l.setContentsMargins(20, 16, 20, 8)
        body_l.setSpacing(0)

        chat_panel = QFrame()
        chat_panel.setObjectName("chatPanel")
        chat_outer = QVBoxLayout(chat_panel)
        chat_outer.setContentsMargins(12, 12, 12, 12)

        self.chat_display = QTextEdit()
        self.chat_display.setObjectName("chatDisplay")
        self.chat_display.setReadOnly(True)
        self.chat_display.setFrameShape(QFrame.NoFrame)
        self.chat_display.setAcceptRichText(True)
        self.chat_display.setUndoRedoEnabled(False)
        self.chat_display.setPlaceholderText("La conversación aparecerá aquí…")
        self.chat_display.document().setDefaultStyleSheet(_CHAT_DOC_CSS)
        self.chat_display.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        chat_outer.addWidget(self.chat_display, stretch=1)

        body_l.addWidget(chat_panel, stretch=1)

        self.status_label = QLabel()
        self.status_label.setObjectName("statusLabel")
        self.status_label.setTextFormat(Qt.TextFormat.RichText)
        self.status_label.setText("Listo")
        body_l.addWidget(self.status_label)

        self.projects_footer = QLabel("")
        self.projects_footer.setObjectName("projectsFooter")
        self.projects_footer.setStyleSheet("color:#71717a;font-size:11px;padding:2px 0 6px 0;")
        self.projects_footer.setWordWrap(True)
        body_l.addWidget(self.projects_footer)

        root.addWidget(body, stretch=1)

        # —— Barra inferior fija ——
        input_wrap = QFrame()
        input_wrap.setObjectName("inputBar")
        input_wrap.setMinimumHeight(112)
        iwl = QVBoxLayout(input_wrap)
        iwl.setContentsMargins(20, 10, 20, 14)
        iwl.setSpacing(8)

        attach_row = QHBoxLayout()
        attach_row.setSpacing(8)
        self.attach_label = QLabel("")
        self.attach_label.setStyleSheet("color:#a1a1aa;font-size:12px;")
        self.attach_label.setWordWrap(True)
        self.attach_label.hide()
        attach_row.addWidget(self.attach_label, stretch=1)

        self.btn_attach_img = QPushButton("Imagen…")
        self.btn_attach_img.setObjectName("attachBtn")
        self.btn_attach_img.setCursor(Qt.PointingHandCursor)
        self.btn_attach_img.clicked.connect(self._pick_image_file)
        attach_row.addWidget(self.btn_attach_img)

        self.btn_attach_pdf = QPushButton("PDF…")
        self.btn_attach_pdf.setObjectName("attachBtn")
        self.btn_attach_pdf.setCursor(Qt.PointingHandCursor)
        self.btn_attach_pdf.clicked.connect(self._pick_pdf_file)
        attach_row.addWidget(self.btn_attach_pdf)

        self.btn_clear_attach = QPushButton("Quitar")
        self.btn_clear_attach.setObjectName("attachBtn")
        self.btn_clear_attach.setCursor(Qt.PointingHandCursor)
        self.btn_clear_attach.clicked.connect(self._clear_attachments)
        attach_row.addWidget(self.btn_clear_attach)

        iwl.addLayout(attach_row)

        row = QHBoxLayout()
        row.setSpacing(12)

        self.input_field = QLineEdit()
        self.input_field.setObjectName("messageInput")
        self.input_field.setPlaceholderText(
            f"Mensaje… · Adjuntos máx. {_GUI_MAX_ATTACHMENTS} / {_GUI_MAX_ATTACH_BYTES // (1024 * 1024)} MB · "
            "Ctrl+V pega captura · Arrastra PNG/JPG/PDF"
        )
        self.input_field.returnPressed.connect(self.handle_send)
        self.input_field.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        row.addWidget(self.input_field, stretch=1)

        self.send_button = QPushButton("Enviar")
        self.send_button.setObjectName("sendButton")
        self.send_button.setCursor(Qt.PointingHandCursor)
        self.send_button.setFixedHeight(48)
        self.send_button.clicked.connect(self.handle_send)
        row.addWidget(self.send_button)

        iwl.addLayout(row)

        root.addWidget(input_wrap)

        self.setAcceptDrops(True)
        self.input_field.installEventFilter(self)
        log.info("Init AARIS GUI...")
        self.init_aaris()
        log.info("AARIS initialized.")
        self.worker = None

    def init_aaris(self):
        log.info("Initializing brain...")
        self.brain = AarisBrain()
        self.brain.initialize()

        log.info("Loading tools...")
        self.available_tools = get_all_tools()
        log.info("Building tool groups...")
        self.tool_groups = build_tool_groups(self.available_tools)
        self.tool_map = {f.__name__: f for f in self.available_tools}

        log.info("Building messages...")
        refresh_system_prompt()
        self.messages = [{"role": "system", "content": SYSTEM_PROMPT}]

        self.chat_display.clear()
        self.append_chat("System", "Sistemas en línea. A la espera de sus órdenes, señor.")
        self._update_projects_footer()

    def append_chat(self, sender, text):
        timestamp = datetime.now().strftime("%H:%M")
        safe_sender = html_module.escape(sender)
        text = _sanitize_chat_display_text(text)
        safe_text = html_module.escape(text).replace("\n", "<br>")

        # QTextEdit: sin flex/gradient/min(); colores sólidos y text-align + inline-block.
        if sender == "You":
            bubble_bg = "#252047"
            border = "#6366f1"
            outer_align = "right"
            name_color = "#c7d2fe"
        elif sender == "A.A.R.I.S.":
            bubble_bg = "#141c2b"
            border = "#38bdf8"
            outer_align = "left"
            name_color = "#7dd3fc"
        else:
            bubble_bg = "#2d2419"
            border = "#d97706"
            outer_align = "left"
            name_color = "#fcd34d"

        html = f"""
<table width="100%" cellspacing="0" cellpadding="0" style="margin-bottom:14px;"><tr>
<td align="{outer_align}" style="padding:0 4px;">
<table cellspacing="0" cellpadding="0" style="max-width:720px; border:1px solid {border};
  background-color:{bubble_bg}; border-radius:16px;">
<tr><td style="padding:12px 16px 14px 16px;">
  <div style="font-size:11px; color:#a1a1aa; margin-bottom:8px;">
    <span style="color:{name_color}; font-weight:700;">{safe_sender}</span>
    <span style="color:#71717a;"> &nbsp;·&nbsp; {timestamp}</span>
  </div>
  <div style="font-size:14px; line-height:1.65; color:#f4f4f5;">{safe_text}</div>
</td></tr></table>
</td></tr></table>
"""
        self.chat_display.append(html.strip())
        sb = self.chat_display.verticalScrollBar()
        sb.setValue(sb.maximum())

    def _update_projects_footer(self) -> None:
        try:
            from aaris.workspace_defaults import ensure_default_code_projects_parent

            p = ensure_default_code_projects_parent()
            if p.startswith("Error"):
                self.projects_footer.setText("")
            else:
                self.projects_footer.setText(f"Código por defecto (sin ruta): {p}")
        except Exception as e:
            log.warning("projects footer: %s", e)
            self.projects_footer.setText("")

    def _open_default_projects_folder(self) -> None:
        try:
            from aaris.workspace_defaults import ensure_default_code_projects_parent

            p = ensure_default_code_projects_parent()
            if p.startswith("Error"):
                self.append_chat("System", p)
                return
            if sys.platform == "win32":
                os.startfile(p)  # type: ignore[attr-defined]
            else:
                import subprocess

                subprocess.run(["xdg-open", p], check=False)
        except Exception as e:
            self.append_chat("System", f"No se pudo abrir la carpeta: {e}")

    def _aaris_inbox(self) -> Path:
        base = Path(os.environ.get("AARIS_APP_DIR", str(Path.home() / ".aaris")))
        inbox = base / "inbox"
        inbox.mkdir(parents=True, exist_ok=True)
        return inbox

    def _copy_into_inbox(self, src_path: str) -> str | None:
        src = Path(src_path).expanduser().resolve()
        if not src.is_file():
            return None
        try:
            sz = src.stat().st_size
        except OSError:
            return None
        if sz > _GUI_MAX_ATTACH_BYTES:
            self.append_chat(
                "System",
                f"Adjunto demasiado grande ({sz // (1024 * 1024)} MB). Máximo {_GUI_MAX_ATTACH_BYTES // (1024 * 1024)} MB "
                "(AARIS_GUI_MAX_ATTACH_BYTES).",
            )
            return None
        dest = self._aaris_inbox() / f"{uuid.uuid4().hex[:14]}_{src.name}"
        shutil.copy2(src, dest)
        return str(dest)

    def _attachments_have_room(self) -> bool:
        if len(self._attachments) >= _GUI_MAX_ATTACHMENTS:
            self.append_chat(
                "System",
                f"Máximo {_GUI_MAX_ATTACHMENTS} adjuntos por mensaje (AARIS_GUI_MAX_ATTACHMENTS). Quite alguno.",
            )
            return False
        return True

    def _add_attachment_file(self, kind: str, path: str) -> None:
        if not self._attachments_have_room():
            return
        copied = self._copy_into_inbox(path)
        if not copied:
            self.append_chat("System", f"No se pudo copiar el adjunto: {path}")
            return
        name = Path(copied).name
        self._attachments.append({"kind": kind, "path": copied, "name": name})
        self._refresh_attach_label()

    def _add_clipboard_image(self) -> bool:
        if not self._attachments_have_room():
            return False
        img = QGuiApplication.clipboard().image()
        if img.isNull():
            return False
        dest = self._aaris_inbox() / f"paste_{uuid.uuid4().hex[:10]}.png"
        if not img.save(str(dest), "PNG"):
            return False
        try:
            if dest.stat().st_size > _GUI_MAX_ATTACH_BYTES:
                dest.unlink(missing_ok=True)
                self.append_chat("System", "La captura pegada supera el tamaño máximo de adjunto.")
                return False
        except OSError:
            pass
        self._attachments.append({"kind": "image", "path": str(dest.resolve()), "name": dest.name})
        self._refresh_attach_label()
        self.append_chat("System", f"Captura pegada: {dest.name}")
        return True

    def _refresh_attach_label(self) -> None:
        if not self._attachments:
            self.attach_label.hide()
            return
        self.attach_label.show()
        parts = [
            f"{a['name']} ({'img' if a['kind'] == 'image' else 'pdf'})"
            for a in self._attachments[:_GUI_MAX_ATTACHMENTS]
        ]
        extra = (
            f" (+{len(self._attachments) - _GUI_MAX_ATTACHMENTS} más)"
            if len(self._attachments) > _GUI_MAX_ATTACHMENTS
            else ""
        )
        self.attach_label.setText("Adjuntos: " + ", ".join(parts) + extra)

    @Slot()
    def _clear_attachments(self) -> None:
        self._attachments.clear()
        self._refresh_attach_label()

    @Slot()
    def _pick_image_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Elegir imagen",
            "",
            "Imágenes (*.png *.jpg *.jpeg *.webp *.gif *.bmp);;Todos (*.*)",
        )
        if path:
            self._add_attachment_file("image", path)

    @Slot()
    def _pick_pdf_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Elegir PDF", "", "PDF (*.pdf);;Todos (*.*)")
        if path:
            self._add_attachment_file("pdf", path)

    def _compose_user_message(self, typed: str) -> str:
        lines = ["---", "[Adjuntos AARIS]"]
        for a in self._attachments:
            lines.append(f"- {a['kind'].upper()}: {a['path']}")
        block = "\n".join(lines)
        if typed.strip():
            merged = f"{typed.strip()}\n\n{block}"
        else:
            merged = (
                f"{block}\n\n"
                "(Instrucción: el usuario solo adjuntó archivos. Para cada IMAGEN usa "
                "`vision_analyze_image(image_path=..., prompt=...)` en español. "
                "Para cada PDF usa `document_ask(file_path=..., question=...)` "
                "o `summarize_document` si pide solo un resumen general.)"
            )
        return merged

    def eventFilter(self, obj, event):
        if obj is self.input_field and event.type() == QEvent.Type.KeyPress:
            if event.matches(QKeySequence.StandardKey.Paste):
                if self._add_clipboard_image():
                    return True
        return super().eventFilter(obj, event)

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            for url in event.mimeData().urls():
                p = (url.toLocalFile() or "").lower()
                if p.endswith((".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".pdf")):
                    event.acceptProposedAction()
                    return
        super().dragEnterEvent(event)

    def dragMoveEvent(self, event):
        if event.mimeData().hasUrls():
            for url in event.mimeData().urls():
                p = (url.toLocalFile() or "").lower()
                if p.endswith((".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".pdf")):
                    event.acceptProposedAction()
                    return
        super().dragMoveEvent(event)

    def dropEvent(self, event):
        if len(self._attachments) >= _GUI_MAX_ATTACHMENTS:
            self.append_chat("System", f"Máximo {_GUI_MAX_ATTACHMENTS} adjuntos por mensaje.")
            event.ignore()
            return
        for url in event.mimeData().urls():
            if len(self._attachments) >= _GUI_MAX_ATTACHMENTS:
                self.append_chat("System", f"Solo se admiten hasta {_GUI_MAX_ATTACHMENTS} adjuntos; el resto se ignoró.")
                break
            path = url.toLocalFile()
            if not path:
                continue
            low = path.lower()
            if low.endswith((".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp")):
                self._add_attachment_file("image", path)
            elif low.endswith(".pdf"):
                self._add_attachment_file("pdf", path)
        self._refresh_attach_label()
        event.acceptProposedAction()

    @Slot()
    def handle_send(self):
        typed = self.input_field.text().strip()
        if not typed and not self._attachments:
            return

        turn_payload = self._compose_user_message(typed)
        self.input_field.clear()
        self._attachments.clear()
        self._refresh_attach_label()

        self.append_chat("You", turn_payload)

        vault_context = self.brain.before_turn(turn_payload)
        if vault_context:
            self.messages.append({"role": "system", "content": vault_context})

        self.messages.append({"role": "user", "content": turn_payload})

        self.input_field.setEnabled(False)
        self.send_button.setEnabled(False)
        for b in (self.btn_attach_img, self.btn_attach_pdf, self.btn_clear_attach):
            b.setEnabled(False)

        turn_opts = _ollama_options_for_turn(turn_payload)
        self.worker = AarisWorker(
            turn_payload,
            self.messages,
            self.available_tools,
            self.tool_groups,
            self.tool_map,
            turn_opts,
        )
        self.worker.response_ready.connect(self.on_bot_reply)
        self.worker.thinking_state.connect(self.on_thinking)
        self.worker.start()

    @Slot(str, str)
    def on_bot_reply(self, sender, text):
        self.append_chat(sender, text)
        self.messages.append({"role": "assistant", "content": text})

        self.messages[:] = prune_messages(self.messages, keep_last=MAX_CONTEXT_MESSAGES)

        user_text = ""
        for m in reversed(self.messages):
            if m.get("role") == "user":
                user_text = m.get("content", "")
                break
        self.brain.after_turn(user_text, text)

        try:
            from voice import VoiceSpeaker

            speaker = VoiceSpeaker()
            speaker.speak_async(text)
        except Exception as e:
            log.warning("Voice error: %s", e)

    @Slot(bool)
    def on_thinking(self, is_thinking):
        for b in (self.btn_attach_img, self.btn_attach_pdf, self.btn_clear_attach):
            b.setEnabled(not is_thinking)
        if is_thinking:
            self.status_label.setText(
                '<span style="color:#fbbf24;">●</span> '
                '<span style="color:#e4e4e7;">Procesando con Ollama…</span>'
            )
        else:
            self.status_label.setText(
                '<span style="color:#4ade80;">●</span> '
                '<span style="color:#a1a1aa;">Listo</span>'
            )
            self.input_field.setEnabled(True)
            self.send_button.setEnabled(True)
            for b in (self.btn_attach_img, self.btn_attach_pdf, self.btn_clear_attach):
                b.setEnabled(True)
            self.input_field.setFocus()

    def closeEvent(self, event):
        try:
            self.brain.shutdown("Sesión GUI cerrada")
        except Exception as e:
            log.warning("brain shutdown: %s", e)
        super().closeEvent(event)


def main() -> None:
    from aaris.logging import configure_logging

    configure_logging()
    log.info("GUI start")
    app = QApplication(sys.argv)
    app.setStyle("Fusion")

    # Suavizar tipografía en Windows si existe la fuente del sistema
    if QFontDatabase().hasFamily("Segoe UI Variable"):
        app.setFont(QFont("Segoe UI Variable", 10))

    window = AarisGUI()
    window.show()
    window.raise_()
    window.activateWindow()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
