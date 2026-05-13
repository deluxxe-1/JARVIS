"""
Carpeta por defecto para proyectos de código cuando el usuario no indica ruta.

La ruta relativa (respecto al directorio de documentos del usuario) se puede
sobreescribir con la variable de entorno ``AARIS_CODE_PROJECTS_REL``
(por defecto ``Documents/Proyectos``; en español ``Documentos/Proyectos`` es equivalente
vía ``resolve_path``).
"""

from __future__ import annotations

import os
from pathlib import Path

_DEFAULT_REL = os.environ.get("AARIS_CODE_PROJECTS_REL", "Documents/Proyectos")


def default_code_projects_parent_resolved() -> str:
    """Devuelve la ruta absoluta de la carpeta padre (sin garantizar que exista)."""
    from aaris.tools.filesystem import resolve_path

    return resolve_path(_DEFAULT_REL, must_exist=False)


def ensure_default_code_projects_parent() -> str:
    """
    Crea si hace falta la carpeta base (p. ej. .../Documents/Proyectos).
    Devuelve la ruta absoluta o un mensaje que empieza por ``Error:``.
    """
    r = default_code_projects_parent_resolved()
    if r.startswith("Error"):
        return r
    try:
        Path(r).mkdir(parents=True, exist_ok=True)
    except OSError as e:
        return f"Error: no se pudo crear {r}: {e}"
    return r


def default_code_workspace_instruction() -> str:
    """Fragmento añadido al system prompt con la ruta real de esta máquina."""
    root = ensure_default_code_projects_parent()
    rel = os.environ.get("AARIS_CODE_PROJECTS_REL", "Documents/Proyectos")
    if root.startswith("Error"):
        return (
            "\n## Directorio por defecto para código\n"
            f"- No se pudo preparar la carpeta de proyectos: {root}\n"
            "- Si el usuario no da ruta, pide aclaración o usa una ruta que él indique.\n"
        )
    return (
        "\n## Directorio por defecto para código (sin ruta del usuario)\n"
        f"- Carpeta base **creada o verificada**: `{root}`\n"
        f"- (Resolución lógica: `{rel}` con `resolve_path`.)\n"
        "- Si el usuario pide **código, script o proyecto** y **no especifica carpeta ni ruta**:\n"
        "  1. Elige un **nombre de carpeta** breve y descriptivo del encargo: minúsculas, ASCII, "
        "palabras con guiones (ej. `cli-tareas`, `api-clima`, `snake-pygame`).\n"
        "  2. Resuelve `Documentos/Proyectos/<nombre>` o `Documents/Proyectos/<nombre>` con `resolve_path` "
        "(equivalente a la base anterior + subcarpeta).\n"
        "  3. `create_folder` si hace falta; luego `create_file` y demás herramientas **dentro** de esa carpeta.\n"
        "- Si el usuario **indica ruta** (absoluta, `Escritorio/...`, `./repo`, etc.), **úsa esa** y no sustituyas por esta base.\n"
    )
