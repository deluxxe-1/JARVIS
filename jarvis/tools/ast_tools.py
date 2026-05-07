import glob as glob_module
import json
import os
import subprocess
from pathlib import Path
import re
import difflib
import shutil
import unicodedata
from typing import Optional, Any
import fnmatch
import uuid
from datetime import datetime, timezone
from functools import lru_cache
import hashlib
import time
from contextlib import contextmanager

from jarvis.tools.core import *

def ast_list_functions(path: str) -> str:
    """
    Lista las clases y funciones de un archivo Python usando parseo AST nativo.
    """
    try:
        resolved = resolve_path(path, must_exist=True)
        if resolved.startswith("Error:"): return resolved
        with open(resolved, "r", encoding="utf-8") as f:
            code = f.read()
        import ast
        tree = ast.parse(code)
        lines = []
        for node in tree.body:
            if isinstance(node, ast.FunctionDef):
                lines.append(f"Function: {node.name}() (line {node.lineno})")
            elif isinstance(node, ast.AsyncFunctionDef):
                lines.append(f"AsyncFunction: {node.name}() (line {node.lineno})")
            elif isinstance(node, ast.ClassDef):
                lines.append(f"Class: {node.name} (line {node.lineno})")
                for sub in node.body:
                    if isinstance(sub, ast.FunctionDef):
                        lines.append(f"  Method: {sub.name}() (line {sub.lineno})")
        return "\n".join(lines) if lines else "No se encontraron funciones o clases en el nivel superior."
    except Exception as e:
        return f"Error en ast_list_functions: {e}"

def ast_read_function(path: str, func_name: str) -> str:
    """
    Extrae el código fuente exacto de una función o clase de un archivo Python usando AST.
    """
    try:
        resolved = resolve_path(path, must_exist=True)
        if resolved.startswith("Error:"): return resolved
        with open(resolved, "r", encoding="utf-8") as f:
            code = f.read()
        import ast
        tree = ast.parse(code)
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                if node.name == func_name:
                    if hasattr(ast, "unparse"): 
                        return ast.unparse(node)
                    return "Error: ast.unparse requiere Python 3.9+"
        return f"No se encontró {func_name} en {path}."
    except Exception as e:
        return f"Error en ast_read_function: {e}"

