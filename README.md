# AARIS (Python) — Ollama local assistant

Asistente local tipo A.A.R.I.S. con:
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

### Instalación como paquete (recomendado)
```bash
pip install -e .
```

### Instalar todo (GUI + voz + OCR + system + web + dev)
```bash
pip install -e ".[all]"
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

### Web/Browser automation
```bash
pip install -r requirements-web.txt
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

O si lo instalas como paquete:
```bash
aaris
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

Adjuntos en la GUI: **Imagen…** / **PDF…**, **Ctrl+V** para pegar una captura del portapapeles, o **arrastrar y soltar** archivos `.png`, `.jpg`, `.webp`, `.pdf`, etc. Los archivos se guardan en `AARIS_APP_DIR/inbox/` y el asistente invoca `vision_analyze_image` (modelo `AARIS_VISION_MODEL`, por defecto `llava` — instalar con `ollama pull llava`) y `document_ask` / `summarize_document` para PDF. Hay límites configurables (`AARIS_GUI_MAX_ATTACHMENTS`, `AARIS_GUI_MAX_ATTACH_BYTES`). Botón **Abrir Proyectos** abre la carpeta por defecto de código (`AARIS_CODE_PROJECTS_REL`). Recomendado: `pip install -r requirements-gui.txt` (incluye Pillow y PyPDF2).

O si lo instalas como paquete:
```bash
aaris-gui
```

## Variables de entorno (resumen)
- `AARIS_MODEL`: modelo que usa el asistente principal (CLI, GUI, `aaris.engine`). Por defecto `qwen2.5:14b`. Tiene prioridad sobre el nombre genérico del README antiguo.
- `OLLAMA_MODEL`: lo usan otros módulos (p. ej. inteligencia, git). Conviene alinearlo con `AARIS_MODEL` para no mezclar modelos.
- `OLLAMA_NUM_CTX`, `OLLAMA_TEMPERATURE`: opciones pasadas a Ollama cuando aplica (la GUI usa temperaturas distintas para charla vs herramientas; ver abajo).
- `AARIS_APP_DIR`: carpeta de datos (default: `~/.aaris`)
- `AARIS_HOTKEY`: hotkey global (default: `win+j`)
- `AARIS_VAULT_KEY`: master key del vault (si usas passwords)
- `AARIS_GOOGLE_API_KEY` + `AARIS_GOOGLE_CX`: búsqueda web opcional vía Google Programmable Search.
- `AARIS_DDG_REGION`: región para búsqueda DDG (por defecto `es-es`).
- `AARIS_GUI_TEMP_TOOLS` / `AARIS_GUI_TEMP_CHAT`: temperatura en la GUI para turnos con/sin herramientas (ver sección siguiente).
- `AARIS_VISION_MODEL`: modelo Ollama **con visión** para `vision_analyze_image` (por defecto `llava`). Ej.: `ollama pull llava` o `ollama pull qwen2-vl`.
- `AARIS_VISION_TEMP`: temperatura para llamadas de visión (por defecto `0.15`).
- `AARIS_OPENWEATHER_API_KEY` (o `OPENWEATHER_API_KEY`): clima vía [OpenWeatherMap](https://openweathermap.org/api); si no está definida, se usa wttr.in.
- `AARIS_NEWSAPI_KEY` (o `NEWSAPI_KEY`): noticias vía [NewsAPI.org](https://newsapi.org/) — en `get_news` usa `search="…"` o categorías `headlines_es`, `headlines_us`, etc.
- `AARIS_IPINFO_TOKEN` (o `IPINFO_TOKEN`): [IPinfo Lite](https://ipinfo.io/developers) para datos de IP/ASN (mejor que el JSON anónimo sin token).
- `AARIS_CODE_PROJECTS_REL`: carpeta base bajo Documentos para **código sin ruta** (por defecto `Documents/Proyectos`). El prompt del sistema se recalcula al arrancar la GUI (`refresh_system_prompt`).
- `AARIS_PLAN_MODE`: `off` \| `auto` \| `confirm` — plan previo antes de herramientas (CLI / motor).
- **GUI adjuntos:** `AARIS_GUI_MAX_ATTACHMENTS` (default 8), `AARIS_GUI_MAX_ATTACH_BYTES` (default 15 MB).
- **HTTP (`aaris.cli --server`):** `AARIS_API_TOKEN` **obligatorio** si el bind no es solo localhost (`127.0.0.1` / `localhost` / `::1`). `AARIS_HTTP_MAX_REQ_PER_MIN` (default 48), `AARIS_HTTP_MAX_BODY_BYTES`, `AARIS_HTTP_HOST`, `AARIS_HTTP_PORT`.

## Modelo Ollama y tool-calling (recomendado leer)

El asistente invoca **muchas funciones** (archivos, web, comandos). La fiabilidad depende sobre todo de:

1. **Versión de Ollama**  
   Mantén [Ollama](https://ollama.com/) actualizado. Los esquemas de *tool calling* y el comportamiento del API cambian entre versiones.

2. **Modelo** (`AARIS_MODEL`)  
   Los modelos locales más pequeños a veces **explican en lugar de llamar tools** o mezclan inglés/meta-texto. En la práctica suelen ir mejor (según época y versión de Ollama):
   - **Qwen2.5** (`qwen2.5:14b`, `qwen2.5:7b`): buen equilibrio instrucción + tools.
   - **Llama 3.1** / **3.2** en tamaños 8B+: razonable con tools si el contexto no es enorme.
   - **Mistral** / **Mixtral**: alternativas habituales; prueba en tu máquina.

   Comprueba que el modelo esté descargado: `ollama pull qwen2.5:14b` y que coincida con `AARIS_MODEL`.

3. **Temperatura baja con herramientas**  
   Con *temperature* alta, el modelo inventa argumentos o evita el formato de función. La **GUI** aplica por defecto **~0.1** en turnos que usan herramientas y algo más alta en charla simple. Puedes forzar:
   - `AARIS_GUI_TEMP_TOOLS` (default `0.1`) — creación de archivos, web, comandos.
   - `AARIS_GUI_TEMP_CHAT` (default `0.35`) — saludos y conversación sin tools.

4. **Contexto** (`OLLAMA_NUM_CTX`)  
   Si el modelo “se pierde” con muchas tools, sube el contexto (según VRAM), p. ej. `set OLLAMA_NUM_CTX=32768` en Windows antes de arrancar.

5. **Si sigue fallando**  
   Reduce herramientas activas (ya hay selector por intención), prueba otro `AARIS_MODEL`, o divide la petición en dos mensajes (primero buscar, luego crear la web).

