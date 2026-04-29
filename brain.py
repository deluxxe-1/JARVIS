"""
JARVIS Brain Module — Cerebro central usando Obsidian como backend.

Todo lo que JARVIS recuerda, aprende, registra y consulta pasa por aquí.
El vault de Obsidian en C:\\Users\\deluxXe\\JARVIS es la única fuente de verdad.

Estructura del vault que este módulo crea automáticamente:
    JARVIS/
    ├── Config/
    │   ├── settings.md          ← configuración de JARVIS
    │   └── user_profile.md      ← quién eres, preferencias
    ├── Memory/
    │   ├── long_term.md         ← hechos importantes permanentes
    │   └── learned_facts.md     ← cosas que JARVIS aprendió de ti
    ├── Sessions/
    │   └── YYYY-MM-DD_N.md      ← una nota por sesión
    ├── Tasks/
    │   ├── pending.md
    │   └── completed.md
    ├── Knowledge/
    │   └── (notas de conocimiento guardadas)
    ├── Tools/
    │   └── usage_log.md         ← registro de qué tools se usan
    └── Logs/
        ├── actions.md           ← acciones ejecutadas
        └── errors.md            ← errores encontrados
"""

from __future__ import annotations

import json
import os
import re
import secrets
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional


# ---------------------------------------------------------------------------
# Configuración del vault
# ---------------------------------------------------------------------------

VAULT_PATH = Path(os.environ.get(
    "JARVIS_VAULT_PATH",
    os.path.join(os.path.expanduser("~"), "JARVIS"),
)).expanduser().resolve()

# Carpetas principales del vault
_FOLDERS = {
    "config":    "Config",
    "memory":    "Memory",
    "sessions":  "Sessions",
    "tasks":     "Tasks",
    "knowledge": "Knowledge",
    "tools":     "Tools",
    "logs":      "Logs",
}

# Cuántas líneas máximo antes de archivar un fichero de log
_MAX_LOG_LINES = 500


# ---------------------------------------------------------------------------
# Utilidades internas
# ---------------------------------------------------------------------------

def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _today() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def _folder(name: str) -> Path:
    """Devuelve la ruta de una carpeta del vault, creándola si no existe."""
    p = VAULT_PATH / _FOLDERS[name]
    p.mkdir(parents=True, exist_ok=True)
    return p


def _read(path: Path) -> str:
    """Lee un fichero del vault. Devuelve '' si no existe."""
    try:
        if path.is_file():
            return path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        pass
    return ""


def _write(path: Path, content: str) -> None:
    """Escribe un fichero del vault de forma atómica."""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(content, encoding="utf-8")
        tmp.replace(path)
    except Exception as e:
        print(f"[Brain] Error escribiendo {path}: {e}")


def _append_line(path: Path, line: str) -> None:
    """Añade una línea al final de un fichero."""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8") as f:
            f.write(line + "\n")
        _rotate_if_needed(path)
    except Exception as e:
        print(f"[Brain] Error en append {path}: {e}")


def _rotate_if_needed(path: Path) -> None:
    """
    Si el fichero supera _MAX_LOG_LINES, archiva la mitad antigua.
    Así los ficheros no crecen indefinidamente.
    """
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
        if len(lines) <= _MAX_LOG_LINES:
            return
        half = len(lines) // 2
        archive_name = path.stem + f"_archive_{_today()}" + path.suffix
        archive_path = path.parent / archive_name
        _write(archive_path, "\n".join(lines[:half]) + "\n")
        _write(path, "\n".join(lines[half:]) + "\n")
    except Exception:
        pass


def _frontmatter(meta: dict[str, Any]) -> str:
    """Genera un bloque frontmatter YAML para Obsidian."""
    lines = ["---"]
    for k, v in meta.items():
        if isinstance(v, list):
            lines.append(f"{k}: [{', '.join(str(x) for x in v)}]")
        elif isinstance(v, bool):
            lines.append(f"{k}: {'true' if v else 'false'}")
        else:
            lines.append(f"{k}: {v}")
    lines.append("---")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Setup inicial — crea la estructura del vault
# ---------------------------------------------------------------------------

def setup_vault() -> str:
    """
    Crea la estructura completa del vault si no existe.
    Llámalo una vez al arrancar JARVIS.
    """
    try:
        VAULT_PATH.mkdir(parents=True, exist_ok=True)

        # Crear todas las carpetas
        for name in _FOLDERS:
            _folder(name)

        # --- Config/settings.md ---
        settings_path = _folder("config") / "settings.md"
        if not settings_path.is_file():
            content = _frontmatter({
                "type": "config",
                "created": _today(),
            }) + """

# ⚙️ JARVIS Settings

Edita este archivo desde Obsidian para cambiar el comportamiento de JARVIS.

## Modelo
```
OLLAMA_MODEL: qwen2.5:14b
```

## Idioma de respuesta
```
language: español
```

## Comportamiento
```
max_tool_rounds: 12
memory_update_every: 5
dry_run: false
plan_mode: off
```

## Personalidad
```
name: J.A.R.V.I.S.
tone: formal
address_user_as: señor
```
"""
            _write(settings_path, content)

        # --- Config/user_profile.md ---
        profile_path = _folder("config") / "user_profile.md"
        if not profile_path.is_file():
            content = _frontmatter({
                "type": "user_profile",
                "created": _today(),
                "tags": ["perfil", "usuario"],
            }) + """

# 👤 Perfil de Usuario

JARVIS actualiza este archivo automáticamente cuando aprende algo nuevo sobre ti.
También puedes editarlo directamente desde Obsidian.

## Información básica
- **Nombre**: (desconocido)
- **Ubicación**: (desconocida)
- **Idioma preferido**: español

## Preferencias técnicas
- **Editor favorito**: (desconocido)
- **Lenguaje de programación preferido**: (desconocido)
- **Sistema operativo**: Windows

## Proyectos activos
*(JARVIS irá añadiendo proyectos aquí)*

## Notas adicionales
*(JARVIS añadirá observaciones aquí)*
"""
            _write(profile_path, content)

        # --- Memory/long_term.md ---
        lt_path = _folder("memory") / "long_term.md"
        if not lt_path.is_file():
            content = _frontmatter({
                "type": "memory",
                "subtype": "long_term",
                "created": _today(),
                "tags": ["memoria", "largo-plazo"],
            }) + """

# 🧠 Memoria a Largo Plazo

JARVIS escribe aquí los hechos más importantes que no debe olvidar nunca.

---

"""
            _write(lt_path, content)

        # --- Memory/learned_facts.md ---
        lf_path = _folder("memory") / "learned_facts.md"
        if not lf_path.is_file():
            content = _frontmatter({
                "type": "memory",
                "subtype": "learned_facts",
                "created": _today(),
                "tags": ["memoria", "hechos-aprendidos"],
            }) + """

# 💡 Hechos Aprendidos

Cosas que JARVIS ha aprendido durante las conversaciones.

| Fecha | Hecho | Importancia |
|-------|-------|-------------|
"""
            _write(lf_path, content)

        # --- Tasks/pending.md ---
        pending_path = _folder("tasks") / "pending.md"
        if not pending_path.is_file():
            content = _frontmatter({
                "type": "tasks",
                "subtype": "pending",
                "created": _today(),
                "tags": ["tareas", "pendiente"],
            }) + """

# 📋 Tareas Pendientes

JARVIS gestiona esta lista automáticamente.
Usa `- [ ]` para tareas pendientes y `- [x]` para completadas.

---

"""
            _write(pending_path, content)

        # --- Tasks/completed.md ---
        completed_path = _folder("tasks") / "completed.md"
        if not completed_path.is_file():
            content = _frontmatter({
                "type": "tasks",
                "subtype": "completed",
                "created": _today(),
                "tags": ["tareas", "completada"],
            }) + """

# ✅ Tareas Completadas

| Fecha | Tarea |
|-------|-------|
"""
            _write(completed_path, content)

        # --- Tools/usage_log.md ---
        tools_path = _folder("tools") / "usage_log.md"
        if not tools_path.is_file():
            content = _frontmatter({
                "type": "tools_log",
                "created": _today(),
                "tags": ["tools", "registro"],
            }) + """

# 🔧 Registro de Uso de Tools

| Fecha/Hora | Tool | Resultado |
|------------|------|-----------|
"""
            _write(tools_path, content)

        # --- Logs/actions.md ---
        actions_path = _folder("logs") / "actions.md"
        if not actions_path.is_file():
            content = _frontmatter({
                "type": "log",
                "subtype": "actions",
                "created": _today(),
                "tags": ["log", "acciones"],
            }) + """

# 📝 Registro de Acciones

Todas las acciones que JARVIS ha ejecutado.

| Fecha/Hora | Acción | Detalle |
|------------|--------|---------|
"""
            _write(actions_path, content)

        # --- Logs/errors.md ---
        errors_path = _folder("logs") / "errors.md"
        if not errors_path.is_file():
            content = _frontmatter({
                "type": "log",
                "subtype": "errors",
                "created": _today(),
                "tags": ["log", "errores"],
            }) + """

# ❌ Registro de Errores

| Fecha/Hora | Error | Contexto |
|------------|-------|---------|
"""
            _write(errors_path, content)

        return f"✅ Vault de JARVIS listo en: {VAULT_PATH}"

    except Exception as e:
        return f"Error en setup_vault: {e}"


# ---------------------------------------------------------------------------
# SESIONES — una nota por conversación
# ---------------------------------------------------------------------------

_current_session_path: Optional[Path] = None
_current_session_id: Optional[str] = None
_turn_count: int = 0


def start_session() -> str:
    """
    Inicia una nueva sesión de conversación.
    Crea una nota en Sessions/ con la fecha y hora actual.
    Retorna el session_id para referencia.
    """
    global _current_session_path, _current_session_id, _turn_count

    try:
        today = _today()
        sessions_dir = _folder("sessions")

        # Buscar cuántas sesiones hay hoy para numerar
        existing = list(sessions_dir.glob(f"{today}_*.md"))
        session_num = len(existing) + 1
        session_id = f"{today}_{session_num}"

        session_path = sessions_dir / f"{session_id}.md"

        now = _now()
        content = _frontmatter({
            "type": "session",
            "date": today,
            "session_id": session_id,
            "started": now,
            "tags": ["sesion", today],
        }) + f"""

# 💬 Sesión {session_id}

**Iniciada:** {now}

---

"""
        _write(session_path, content)

        _current_session_path = session_path
        _current_session_id = session_id
        _turn_count = 0

        return session_id

    except Exception as e:
        return f"error_{secrets.token_hex(4)}"


def log_turn(user_input: str, assistant_response: str) -> None:
    """
    Registra un turno de conversación en la sesión actual.
    """
    global _turn_count

    if _current_session_path is None:
        start_session()

    try:
        _turn_count += 1
        now = _now()
        entry = f"""## Turno {_turn_count} — {now}

**🧑 Tú:** {user_input.strip()}

**🤖 JARVIS:** {assistant_response.strip()[:2000]}{"..." if len(assistant_response) > 2000 else ""}

---

"""
        with open(_current_session_path, "a", encoding="utf-8") as f:
            f.write(entry)

    except Exception as e:
        print(f"[Brain] Error en log_turn: {e}")


def end_session(summary: str = "") -> None:
    """
    Cierra la sesión actual añadiendo un resumen al final.
    """
    global _current_session_path, _current_session_id

    if _current_session_path is None:
        return

    try:
        now = _now()
        footer = f"""
---

## 📊 Resumen de sesión

**Terminada:** {now}
**Turnos:** {_turn_count}
**Resumen:** {summary or "(sin resumen)"}
"""
        with open(_current_session_path, "a", encoding="utf-8") as f:
            f.write(footer)

        _current_session_path = None
        _current_session_id = None

    except Exception as e:
        print(f"[Brain] Error en end_session: {e}")


# ---------------------------------------------------------------------------
# MEMORIA — recordar y recuperar hechos
# ---------------------------------------------------------------------------

def remember(fact: str, importance: str = "medium", category: str = "general") -> str:
    """
    Guarda un hecho importante en la memoria a largo plazo.

    Args:
        fact: El hecho a recordar (texto libre).
        importance: 'low', 'medium' o 'high'.
        category: Categoría del hecho (preferencia, proyecto, técnico, etc.).
    """
    try:
        now = _now()
        emoji = {"high": "🔴", "medium": "🟡", "low": "🟢"}.get(importance, "⚪")

        # Añadir a long_term.md
        lt_path = _folder("memory") / "long_term.md"
        entry = f"- {emoji} **[{category}]** {fact} *(recordado: {now})*\n"
        _append_line(lt_path, entry)

        # Añadir a la tabla de learned_facts.md
        lf_path = _folder("memory") / "learned_facts.md"
        fact_clean = fact.replace("|", "\\|")
        row = f"| {now} | {fact_clean} | {importance} |\n"
        _append_line(lf_path, row)

        return f"✅ Recordado: {fact}"

    except Exception as e:
        return f"Error en remember: {e}"


def recall(query: str, max_results: int = 5) -> str:
    """
    Busca hechos relevantes en la memoria.
    Busca en: long_term.md, learned_facts.md, actions.md y sesiones recientes.

    Args:
        query: Texto a buscar.
        max_results: Máximo de resultados.
    """
    try:
        query_lower = query.lower()
        results = []

        # 1. Buscar en long_term.md (memoria principal)
        lt_path = _folder("memory") / "long_term.md"
        mem_content = _read(lt_path)
        for line in mem_content.splitlines():
            if line.startswith("- ") and query_lower in line.lower():
                results.append(line.strip())
                if len(results) >= max_results:
                    break

        # 2. Buscar en learned_facts.md
        if len(results) < max_results:
            lf_path = _folder("memory") / "learned_facts.md"
            lf_content = _read(lf_path)
            for line in lf_content.splitlines():
                if "|" in line and query_lower in line.lower() and not line.startswith("|---"):
                    if "Fecha" not in line and "Hecho" not in line:
                        results.append(line.strip())
                        if len(results) >= max_results:
                            break

        # 3. Buscar en actions.md (acciones ejecutadas — archivos creados, comandos, etc.)
        if len(results) < max_results:
            actions_path = _folder("logs") / "actions.md"
            actions_content = _read(actions_path)
            for line in actions_content.splitlines():
                if "|" in line and query_lower in line.lower() and not line.startswith("|---"):
                    if "Fecha" not in line and "Acción" not in line:
                        results.append("📋 Acción anterior: " + line.strip())
                        if len(results) >= max_results:
                            break

        # 4. Buscar en sesiones recientes (últimas 3)
        if len(results) < max_results:
            sessions_dir = _folder("sessions")
            session_files = sorted(sessions_dir.glob("*.md"), reverse=True)[:3]
            for sf in session_files:
                if len(results) >= max_results:
                    break
                sf_content = _read(sf)
                lines = sf_content.splitlines()
                for i, line in enumerate(lines):
                    if query_lower in line.lower() and len(line.strip()) > 10:
                        # Incluir algo de contexto (línea anterior y posterior)
                        ctx_start = max(0, i - 1)
                        ctx_end = min(len(lines), i + 2)
                        ctx = " ".join(l.strip() for l in lines[ctx_start:ctx_end] if l.strip())
                        snippet = f"🗂 Sesión {sf.stem}: {ctx[:200]}"
                        if snippet not in results:
                            results.append(snippet)
                        if len(results) >= max_results:
                            break

        if not results:
            return ""

        return "Memoria relevante:\n" + "\n".join(results)

    except Exception:
        return ""


def update_user_profile(key: str, value: str) -> str:
    """
    Actualiza el perfil de usuario en Config/user_profile.md.

    Args:
        key: Campo a actualizar (ej: 'nombre', 'editor favorito').
        value: Nuevo valor.
    """
    try:
        profile_path = _folder("config") / "user_profile.md"
        content = _read(profile_path)

        if not content:
            # Si no existe, crear con setup_vault
            setup_vault()
            content = _read(profile_path)

        now = _now()
        # Añadir al final de la sección de notas
        addition = f"\n- **{key}**: {value} *(actualizado: {now})*"

        # Buscar si ya existe esa clave para actualizarla
        pattern = re.compile(rf"- \*\*{re.escape(key)}\*\*:.*", re.IGNORECASE)
        if pattern.search(content):
            content = pattern.sub(
                f"- **{key}**: {value} *(actualizado: {now})*",
                content,
                count=1,
            )
        else:
            # Añadir en la sección de notas adicionales
            if "## Notas adicionales" in content:
                content = content.replace(
                    "## Notas adicionales\n*(JARVIS añadirá observaciones aquí)*",
                    f"## Notas adicionales{addition}",
                )
            else:
                content += addition + "\n"

        _write(profile_path, content)
        return f"✅ Perfil actualizado: {key} = {value}"

    except Exception as e:
        return f"Error en update_user_profile: {e}"


def get_user_profile() -> str:
    """
    Lee el perfil de usuario para incluirlo como contexto en las respuestas.
    """
    try:
        profile_path = _folder("config") / "user_profile.md"
        content = _read(profile_path)
        if not content:
            return ""
        # Quitar el frontmatter
        if content.startswith("---"):
            parts = content.split("---", 2)
            if len(parts) >= 3:
                return parts[2].strip()
        return content.strip()
    except Exception:
        return ""


def get_settings() -> dict[str, Any]:
    """
    Lee la configuración de JARVIS desde Config/settings.md.
    Devuelve un dict con los valores encontrados.
    """
    try:
        settings_path = _folder("config") / "settings.md"
        content = _read(settings_path)
        settings: dict[str, Any] = {}

        # Parsear bloques de código con clave: valor
        for match in re.finditer(r"```\n(.*?)\n```", content, re.DOTALL):
            block = match.group(1)
            for line in block.splitlines():
                if ":" in line:
                    k, v = line.split(":", 1)
                    settings[k.strip()] = v.strip()

        return settings

    except Exception:
        return {}


# ---------------------------------------------------------------------------
# TAREAS
# ---------------------------------------------------------------------------

def add_task(task: str, due: str = "", priority: str = "normal") -> str:
    """
    Añade una tarea pendiente en Tasks/pending.md.

    Args:
        task: Descripción de la tarea.
        due: Fecha límite (ej: '2026-04-30') o texto libre (ej: 'el viernes').
        priority: 'alta', 'normal' o 'baja'.
    """
    try:
        pending_path = _folder("tasks") / "pending.md"
        now = _now()
        priority_emoji = {"alta": "🔴", "normal": "🟡", "baja": "🟢"}.get(priority, "⚪")
        due_str = f" 📅 {due}" if due else ""
        entry = f"- [ ] {priority_emoji} {task}{due_str} *(añadida: {now})*\n"
        _append_line(pending_path, entry)
        return f"✅ Tarea añadida: {task}"
    except Exception as e:
        return f"Error en add_task: {e}"


def complete_task(task_description: str) -> str:
    """
    Marca una tarea como completada.
    La mueve de pending.md a completed.md.

    Args:
        task_description: Parte del texto de la tarea a buscar.
    """
    try:
        pending_path = _folder("tasks") / "pending.md"
        completed_path = _folder("tasks") / "completed.md"

        content = _read(pending_path)
        lines = content.splitlines(keepends=True)

        found = None
        new_lines = []
        for line in lines:
            if (
                task_description.lower() in line.lower()
                and "- [ ]" in line
                and found is None
            ):
                found = line.strip().replace("- [ ]", "").strip()
                # No añadimos esta línea (la eliminamos de pending)
            else:
                new_lines.append(line)

        if not found:
            return f"No encontré la tarea: '{task_description}'"

        _write(pending_path, "".join(new_lines))

        # Añadir a completed.md
        now = _now()
        row = f"| {now} | {found} |\n"
        _append_line(completed_path, row)

        return f"✅ Tarea completada: {found}"

    except Exception as e:
        return f"Error en complete_task: {e}"


def get_pending_tasks() -> str:
    """
    Devuelve las tareas pendientes como texto para incluir en el contexto.
    """
    try:
        pending_path = _folder("tasks") / "pending.md"
        content = _read(pending_path)
        tasks = [
            line.strip()
            for line in content.splitlines()
            if line.strip().startswith("- [ ]")
        ]
        if not tasks:
            return ""
        return "Tareas pendientes:\n" + "\n".join(tasks[:10])
    except Exception:
        return ""


# ---------------------------------------------------------------------------
# CONOCIMIENTO
# ---------------------------------------------------------------------------

def save_knowledge(title: str, content: str, tags: list[str] | None = None, folder: str = "") -> str:
    """
    Guarda una nota de conocimiento en Knowledge/.

    Args:
        title: Título de la nota.
        content: Contenido en markdown.
        tags: Lista de tags para Obsidian.
        folder: Subcarpeta dentro de Knowledge/ (opcional).
    """
    try:
        tags = tags or []
        now = _now()
        knowledge_dir = _folder("knowledge")

        if folder:
            target_dir = knowledge_dir / folder
            target_dir.mkdir(exist_ok=True)
        else:
            target_dir = knowledge_dir

        # Nombre de archivo seguro
        safe_title = re.sub(r'[<>:"/\\|?*]', "", title).strip()
        if not safe_title:
            safe_title = f"nota_{secrets.token_hex(4)}"

        file_path = target_dir / f"{safe_title}.md"

        # Evitar sobreescritura
        counter = 1
        while file_path.exists():
            file_path = target_dir / f"{safe_title}_{counter}.md"
            counter += 1

        note_content = _frontmatter({
            "type": "knowledge",
            "title": title,
            "created": now,
            "tags": tags + ["knowledge"],
        }) + f"\n\n# {title}\n\n{content}\n"

        _write(file_path, note_content)
        rel = str(file_path.relative_to(VAULT_PATH))
        return f"✅ Conocimiento guardado: {rel}"

    except Exception as e:
        return f"Error en save_knowledge: {e}"


def search_knowledge(query: str, max_results: int = 5) -> str:
    """
    Busca en todas las notas de Knowledge/ por palabras clave.
    """
    try:
        query_lower = query.lower()
        knowledge_dir = _folder("knowledge")
        results = []

        for md_file in knowledge_dir.rglob("*.md"):
            content = _read(md_file)
            if query_lower in content.lower():
                # Extraer un preview relevante
                lines = content.splitlines()
                preview_lines = []
                for line in lines:
                    if query_lower in line.lower():
                        preview_lines.append(line.strip())
                        if len(preview_lines) >= 2:
                            break

                rel = str(md_file.relative_to(VAULT_PATH))
                results.append({
                    "file": rel,
                    "preview": " ".join(preview_lines)[:200],
                })

                if len(results) >= max_results:
                    break

        if not results:
            return ""

        lines_out = [f"Conocimiento relevante encontrado:"]
        for r in results:
            lines_out.append(f"- **{r['file']}**: {r['preview']}")
        return "\n".join(lines_out)

    except Exception:
        return ""


# ---------------------------------------------------------------------------
# LOGS
# ---------------------------------------------------------------------------

def log_action(tool: str, args_summary: str, result_summary: str) -> None:
    """
    Registra una acción ejecutada por JARVIS en Logs/actions.md.
    """
    try:
        actions_path = _folder("logs") / "actions.md"
        now = _now()
        args_clean = args_summary.replace("|", "\\|")[:80]
        result_clean = result_summary.replace("|", "\\|")[:80]
        row = f"| {now} | `{tool}` | {args_clean} → {result_clean} |\n"
        _append_line(actions_path, row)
    except Exception:
        pass


def log_error(error: str, context: str = "") -> None:
    """
    Registra un error en Logs/errors.md.
    """
    try:
        errors_path = _folder("logs") / "errors.md"
        now = _now()
        err_clean = error.replace("|", "\\|")[:100]
        ctx_clean = context.replace("|", "\\|")[:80]
        row = f"| {now} | {err_clean} | {ctx_clean} |\n"
        _append_line(errors_path, row)
    except Exception:
        pass


def log_tool_usage(tool_name: str, success: bool) -> None:
    """
    Registra el uso de una tool en Tools/usage_log.md.
    """
    try:
        tools_path = _folder("tools") / "usage_log.md"
        now = _now()
        status = "✅" if success else "❌"
        row = f"| {now} | `{tool_name}` | {status} |\n"
        _append_line(tools_path, row)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# CONTEXTO — lo que JARVIS inyecta antes de responder
# ---------------------------------------------------------------------------

def _is_memory_query(text: str) -> bool:
    """Detecta si el usuario está preguntando por algo de sesiones anteriores."""
    memory_keywords = [
        "recuerdas", "recuerda", "te acuerdas", "mencioné", "dije",
        "hicimos", "hiciste", "creaste", "creé", "sesión anterior",
        "sesión pasada", "antes", "anteriormente", "la última vez",
        "el otro día", "ya hablamos", "ya te dije", "sabes que",
        "remember", "last session", "last time", "we talked about",
    ]
    t = text.lower()
    return any(k in t for k in memory_keywords)


def get_recent_actions(max_lines: int = 10) -> str:
    """
    Lee las últimas acciones del log de acciones para incluirlas como contexto.
    """
    try:
        actions_path = _folder("logs") / "actions.md"
        content = _read(actions_path)
        if not content:
            return ""
        # Coger las últimas líneas con datos (no headers ni separadores)
        data_lines = [
            line.strip() for line in content.splitlines()
            if "|" in line
            and not line.startswith("|---")
            and "Fecha" not in line
            and "Acción" not in line
            and len(line.strip()) > 5
        ]
        recent = data_lines[-max_lines:]
        if not recent:
            return ""
        return "Acciones recientes ejecutadas:\n" + "\n".join(recent)
    except Exception:
        return ""


def build_context_for_response(user_input: str) -> str:
    """
    Construye el contexto relevante del vault para incluir antes de responder.
    Combina: perfil + tareas pendientes + memoria relevante + conocimiento + acciones recientes.

    Este texto se inyecta como mensaje de sistema antes de cada respuesta.
    """
    parts = []

    # 1. Perfil de usuario (siempre incluido, pero resumido)
    profile = get_user_profile()
    if profile:
        profile_lines = [
            l for l in profile.splitlines()
            if l.strip() and not l.startswith("#") and l.startswith("-")
        ][:8]
        if profile_lines:
            parts.append("**Perfil del usuario:**\n" + "\n".join(profile_lines))

    # 2. Tareas pendientes (siempre incluidas)
    tasks = get_pending_tasks()
    if tasks:
        parts.append(tasks)

    # 3. Memoria relevante a la query (incluye acciones pasadas y sesiones)
    memory = recall(user_input, max_results=6)
    if memory:
        parts.append(memory)

    # 4. Si el usuario pregunta por algo que hicimos, incluir acciones recientes completas
    if _is_memory_query(user_input):
        recent_actions = get_recent_actions(max_lines=15)
        if recent_actions:
            parts.append(recent_actions)

    # 5. Conocimiento relevante a la query
    knowledge = search_knowledge(user_input, max_results=3)
    if knowledge:
        parts.append(knowledge)

    if not parts:
        return ""

    header = "═" * 40 + "\n📚 CONTEXTO DEL VAULT DE JARVIS\n" + "═" * 40
    footer = "═" * 40
    return header + "\n\n" + "\n\n".join(parts) + "\n\n" + footer


# ---------------------------------------------------------------------------
# EXTRACCIÓN AUTOMÁTICA DE MEMORIA — analiza respuestas para aprender
# ---------------------------------------------------------------------------

def extract_and_remember(user_input: str, assistant_response: str) -> None:
    """
    Analiza la conversación y guarda automáticamente hechos importantes.
    Llamado después de cada respuesta de JARVIS.

    Detecta: preferencias, nombre/ubicación, y acciones confirmadas por JARVIS.
    """
    try:
        # ── Preferencias del usuario ────────────────────────────────────
        preference_patterns = [
            (r"(prefiero|me gusta|uso|utilizo)\s+([\w\s]+)", "preferencia"),
            (r"mi\s+(editor|ide|terminal|navegador|lenguaje)\s+es\s+([\w\s]+)", "herramienta"),
            (r"trabajo\s+con\s+([\w\s]+)", "tecnología"),
            (r"mi\s+(proyecto|servidor|base de datos)\s+([\w\s]+)", "proyecto"),
        ]
        for pattern, category in preference_patterns:
            match = re.search(pattern, user_input.lower())
            if match:
                fact = match.group(0).strip()
                if 5 < len(fact) < 100:
                    remember(fact, importance="medium", category=category)

        # ── Nombre del usuario ──────────────────────────────────────────
        name_match = re.search(
            r"(me llamo|mi nombre es|soy)\s+([A-Z][a-záéíóúñ]+)",
            user_input,
            re.IGNORECASE,
        )
        if name_match:
            name = name_match.group(2)
            update_user_profile("Nombre", name)
            remember(f"El usuario se llama {name}", importance="high", category="identidad")

        # ── Ubicación del usuario ───────────────────────────────────────
        location_match = re.search(
            r"(vivo en|estoy en|soy de)\s+([\w\s,]+)",
            user_input,
            re.IGNORECASE,
        )
        if location_match:
            location = location_match.group(2).strip()
            if len(location) < 50:
                update_user_profile("Ubicación", location)

        # ── Acciones confirmadas en la respuesta de JARVIS ──────────────
        # Si JARVIS confirma una acción, la memoriza para sesiones futuras.
        resp_lower = assistant_response.lower()
        action_confirmations = [
            # Patrón de confirmación, categoría
            (r"(he creado|creado correctamente|archivo creado)[^.\n]{0,80}", "accion_archivo"),
            (r"(he creado|creada correctamente|carpeta creada)[^.\n]{0,80}", "accion_carpeta"),
            (r"(he editado|editado correctamente|archivo actualizado)[^.\n]{0,80}", "accion_archivo"),
            (r"(he ejecutado|comando ejecutado|ejecutado correctamente)[^.\n]{0,80}", "accion_comando"),
            (r"(he movido|movido a|se ha movido)[^.\n]{0,80}", "accion_archivo"),
            (r"(he eliminado|eliminado correctamente|borrado)[^.\n]{0,80}", "accion_archivo"),
            (r"(instalado correctamente|paquete instalado)[^.\n]{0,80}", "accion_sistema"),
        ]
        for pattern, category in action_confirmations:
            match = re.search(pattern, resp_lower)
            if match:
                snippet = match.group(0).strip()
                # Combinar con lo que pidió el usuario para dar contexto
                fact = f"{snippet} (pedido: {user_input[:80]})"
                if len(fact) > 15:
                    remember(fact, importance="medium", category=category)

    except Exception as e:
        log_error(f"extract_and_remember: {e}", user_input[:50])


# ---------------------------------------------------------------------------
# API pública — punto de entrada único para _legacy_main.py
# ---------------------------------------------------------------------------

class JarvisBrain:
    """
    Interfaz principal del cerebro de JARVIS.
    Úsala así en _legacy_main.py:

        brain = JarvisBrain()
        brain.initialize()

        # Antes de cada turno:
        context = brain.before_turn(user_input)
        messages.append({"role": "system", "content": context})

        # Después de cada turno:
        brain.after_turn(user_input, reply_content, tool_calls_log)
    """

    def __init__(self, vault_path: Optional[str] = None):
        global VAULT_PATH
        if vault_path:
            VAULT_PATH = Path(vault_path).expanduser().resolve()

    def initialize(self) -> str:
        """Configura el vault y arranca la sesión. Llámalo al iniciar JARVIS."""
        result = setup_vault()
        session_id = start_session()
        print(f"[Brain] {result}")
        print(f"[Brain] Sesión iniciada: {session_id}")
        return session_id

    def before_turn(self, user_input: str) -> str:
        """
        Construye el contexto del vault para inyectar antes de responder.
        Retorna un string para añadir como mensaje de sistema.
        """
        ctx = build_context_for_response(user_input)
        return ctx

    def after_turn(
        self,
        user_input: str,
        assistant_response: str,
        tool_calls_log: list[dict] | None = None,
    ) -> None:
        """
        Procesa lo ocurrido después de cada turno:
        - Guarda la conversación en la sesión
        - Extrae y recuerda hechos nuevos
        - Registra las tools usadas
        - Memoriza automáticamente acciones significativas para recuperarlas entre sesiones
        """
        # Guardar en sesión
        log_turn(user_input, assistant_response)

        # Aprender de la conversación (preferencias, nombres, etc.)
        extract_and_remember(user_input, assistant_response)

        # Registrar tools usadas y MEMORIZAR acciones significativas
        if tool_calls_log:
            for tc in tool_calls_log:
                tool_name = tc.get("name", "")
                result_preview = str(tc.get("result_preview", ""))
                args = tc.get("arguments", {}) or {}
                success = not result_preview.startswith("Error")

                if tool_name:
                    log_tool_usage(tool_name, success)
                    log_action(
                        tool=tool_name,
                        args_summary=str(args)[:80],
                        result_summary=result_preview[:80],
                    )

                # ── MEMORIZAR ACCIONES SIGNIFICATIVAS ──────────────────────
                # Guardamos en long_term.md para que recall() pueda encontrarlo
                # en sesiones futuras. Solo acciones exitosas.
                if success and tool_name:
                    _memorable_tools = {
                        "create_file":   lambda a, r: f"Se creó el archivo '{a.get('path', '')}'. Contexto: {user_input[:80]}",
                        "create_folder": lambda a, r: f"Se creó la carpeta '{a.get('path', '')}'. Contexto: {user_input[:80]}",
                        "edit_file":     lambda a, r: f"Se editó el archivo '{a.get('path', '')}'. Contexto: {user_input[:80]}",
                        "search_replace_in_file": lambda a, r: f"Se modificó el archivo '{a.get('path', '')}'. Contexto: {user_input[:80]}",
                        "delete_path":   lambda a, r: f"Se eliminó '{a.get('path', '')}'. Contexto: {user_input[:80]}",
                        "move_path":     lambda a, r: f"Se movió '{a.get('from_path', '')}' a '{a.get('to_path', '')}'. Contexto: {user_input[:80]}",
                        "copy_path":     lambda a, r: f"Se copió '{a.get('from_path', '')}' a '{a.get('to_path', '')}'. Contexto: {user_input[:80]}",
                        "run_command":   lambda a, r: f"Se ejecutó el comando: {a.get('command', '')[:60]}. Contexto: {user_input[:60]}",
                        "append_file":   lambda a, r: f"Se añadió contenido al archivo '{a.get('path', '')}'. Contexto: {user_input[:80]}",
                        "git_smart_commit": lambda a, r: f"Se hizo commit git: {a.get('message', r[:60])}",
                        "install_packages": lambda a, r: f"Se instalaron paquetes: {a.get('packages', '')}",
                    }
                    if tool_name in _memorable_tools:
                        try:
                            fact = _memorable_tools[tool_name](args, result_preview)
                            if fact and len(fact) > 10:
                                remember(fact, importance="medium", category="accion")
                        except Exception:
                            pass

                if not success and tool_name:
                    log_error(
                        error=result_preview[:100],
                        context=f"tool={tool_name}",
                    )

    def shutdown(self, summary: str = "") -> None:
        """Cierra la sesión correctamente al salir de JARVIS."""
        end_session(summary)
        print("[Brain] Sesión guardada en el vault de Obsidian.")

    # Métodos de acceso directo (para usar desde JARVIS como tools)
    def remember(self, fact: str, importance: str = "medium") -> str:
        return remember(fact, importance)

    def add_task(self, task: str, due: str = "") -> str:
        return add_task(task, due)

    def complete_task(self, task: str) -> str:
        return complete_task(task)

    def save_knowledge(self, title: str, content: str, tags: list[str] | None = None) -> str:
        return save_knowledge(title, content, tags)

    def vault_status(self) -> str:
        """Devuelve un resumen del estado del vault."""
        try:
            knowledge_count = len(list(_folder("knowledge").rglob("*.md")))
            sessions_count = len(list(_folder("sessions").glob("*.md")))
            pending_tasks = get_pending_tasks().count("- [ ]")

            return json.dumps({
                "vault_path": str(VAULT_PATH),
                "sessions": sessions_count,
                "knowledge_notes": knowledge_count,
                "pending_tasks": pending_tasks,
                "current_session": _current_session_id,
            }, ensure_ascii=False)
        except Exception as e:
            return f"Error en vault_status: {e}"
