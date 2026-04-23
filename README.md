# JARVIS (Python) — Ollama local assistant

Asistente local tipo J.A.R.V.I.S. con:
- **CLI** (`main.py`)
- **GUI** (PySide6, `gui.py`)
- **Voz** (STT/TTS)
- **Tools** para sistema/archivos/red, etc.

## Requisitos
- Python 3.10+ (recomendado 3.12)
- [Ollama](https://ollama.com/) instalado y corriendo

## Instalación (recomendada por perfiles)

### Base (CLI + LLM)
```bash
pip install -r requirements.txt
```

### GUI
```bash
pip install -r requirements-gui.txt
```

### Voz (STT/TTS)
```bash
pip install -r requirements-voice.txt
```

### OCR + Documentos
```bash
pip install -r requirements-ocr.txt
```

### Sistema (hotkeys, monitor, cifrado, requests)
```bash
pip install -r requirements-system.txt
```

### Dev / tests
```bash
pip install -r requirements-dev.txt
pytest
```

## Ejecutar

### CLI
```bash
python main.py
```

### Ejecutar un prompt (útil para scripting)
```bash
python main.py --run-prompt "hola"
```

### Servidor HTTP
```bash
python main.py --server
```

### GUI
```bash
python gui.py
```

## Variables de entorno (resumen)
- `OLLAMA_MODEL`: modelo principal (default depende del código)
- `JARVIS_APP_DIR`: carpeta de datos (default: `~/.jarvis`)
- `JARVIS_HOTKEY`: hotkey global (default: `win+j`)
- `JARVIS_VAULT_KEY`: master key del vault (si usas passwords)

