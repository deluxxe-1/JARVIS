"""
JARVIS Voice Module — STT (Speech-to-Text) y TTS (Text-to-Speech) para Windows.

Usa `speech_recognition` con Google STT para reconocimiento de voz
y `pyttsx3` con SAPI5 (nativo Windows) para síntesis de voz.
"""

import os
import threading
import queue
import re
from typing import Optional


# ---------------------------------------------------------------------------
# Configuración vía variables de entorno
# ---------------------------------------------------------------------------

VOICE_LANG = os.environ.get("JARVIS_VOICE_LANG", "es-ES")
VOICE_RATE = int(os.environ.get("JARVIS_VOICE_RATE", "180"))       # palabras por minuto
VOICE_VOLUME = float(os.environ.get("JARVIS_VOICE_VOLUME", "1.0"))  # 0.0 a 1.0
WAKE_WORD = os.environ.get("JARVIS_WAKE_WORD", "jarvis").lower()
LISTEN_TIMEOUT = int(os.environ.get("JARVIS_LISTEN_TIMEOUT", "5"))
PHRASE_TIME_LIMIT = int(os.environ.get("JARVIS_PHRASE_TIME_LIMIT", "15"))
ENERGY_THRESHOLD = int(os.environ.get("JARVIS_ENERGY_THRESHOLD", "300"))


# ---------------------------------------------------------------------------
# Voice Speaker — TTS con pyttsx3
# ---------------------------------------------------------------------------

class VoiceSpeaker:
    """Síntesis de voz usando pyttsx3 (SAPI5 en Windows, espeak en Linux)."""

    def __init__(
        self,
        rate: int = VOICE_RATE,
        volume: float = VOICE_VOLUME,
        voice_id: Optional[str] = None,
    ):
        self._rate = rate
        self._volume = volume
        self._voice_id = voice_id
        self._engine = None
        self._queue: queue.Queue[Optional[str]] = queue.Queue()
        self._thread: Optional[threading.Thread] = None
        self._running = False

    def _init_engine(self):
        """Inicializa el motor TTS (debe llamarse en el hilo que lo va a usar)."""
        try:
            import pyttsx3
            engine = pyttsx3.init("sapi5")
        except Exception:
            try:
                import pyttsx3
                engine = pyttsx3.init()  # fallback a driver por defecto
            except Exception as e:
                raise RuntimeError(f"No se pudo inicializar pyttsx3: {e}")

        engine.setProperty("rate", self._rate)
        engine.setProperty("volume", self._volume)

        # Intentar seleccionar voz en español si está disponible
        if self._voice_id:
            engine.setProperty("voice", self._voice_id)
        else:
            voices = engine.getProperty("voices")
            lang_lower = VOICE_LANG.lower().replace("-", "_")
            for v in voices:
                # Buscar voz que coincida con el idioma configurado
                v_id_lower = (v.id or "").lower()
                v_name_lower = (v.name or "").lower()
                langs = [l.lower() for l in (v.languages or [])] if v.languages else []
                if (
                    lang_lower in v_id_lower
                    or lang_lower[:2] in v_id_lower
                    or "spanish" in v_name_lower
                    or "español" in v_name_lower
                    or any(lang_lower[:2] in l for l in langs)
                ):
                    engine.setProperty("voice", v.id)
                    break

        return engine

    def speak(self, text: str) -> None:
        """Habla un texto de forma síncrona (bloquea hasta que termine)."""
        if not text or not text.strip():
            return
        try:
            if self._engine is None:
                self._engine = self._init_engine()
            # Limpiar markdown/caracteres especiales para lectura natural
            clean = _clean_for_speech(text)
            if clean.strip():
                self._engine.say(clean)
                self._engine.runAndWait()
        except Exception as e:
            print(f"[VoiceSpeaker] Error en speak: {e}")

    def speak_async(self, text: str) -> None:
        """Encola texto para hablar en un hilo de fondo."""
        if not text or not text.strip():
            return
        self._queue.put(text)
        if not self._running:
            self._start_worker()

    def _start_worker(self):
        """Lanza el hilo de TTS."""
        self._running = True
        self._thread = threading.Thread(target=self._worker_loop, daemon=True)
        self._thread.start()

    def _worker_loop(self):
        """Loop del hilo de TTS — procesa la cola de mensajes."""
        try:
            engine = self._init_engine()
            while True:
                text = self._queue.get()
                if text is None:
                    break
                clean = _clean_for_speech(text)
                if clean.strip():
                    engine.say(clean)
                    engine.runAndWait()
                self._queue.task_done()
        except Exception as e:
            print(f"[VoiceSpeaker] Error en worker: {e}")
        finally:
            self._running = False

    def stop(self):
        """Detiene el hilo de TTS."""
        self._queue.put(None)
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=5)

    def list_voices(self) -> list[dict[str, str]]:
        """Lista todas las voces TTS disponibles en el sistema."""
        try:
            if self._engine is None:
                self._engine = self._init_engine()
            voices = self._engine.getProperty("voices")
            return [
                {
                    "id": v.id,
                    "name": v.name or "",
                    "languages": str(v.languages or []),
                }
                for v in voices
            ]
        except Exception as e:
            return [{"error": str(e)}]


# ---------------------------------------------------------------------------
# Voice Listener — STT con speech_recognition
# ---------------------------------------------------------------------------

class VoiceListener:
    """Reconocimiento de voz usando speech_recognition + Google STT."""

    def __init__(
        self,
        language: str = VOICE_LANG,
        energy_threshold: int = ENERGY_THRESHOLD,
        listen_timeout: int = LISTEN_TIMEOUT,
        phrase_time_limit: int = PHRASE_TIME_LIMIT,
    ):
        self._language = language
        self._energy_threshold = energy_threshold
        self._listen_timeout = listen_timeout
        self._phrase_time_limit = phrase_time_limit
        self._recognizer = None
        self._microphone = None

    def _init(self):
        """Inicializa recognizer y micrófono."""
        if self._recognizer is not None:
            return
        try:
            import speech_recognition as sr
            self._recognizer = sr.Recognizer()
            self._recognizer.energy_threshold = self._energy_threshold
            self._recognizer.dynamic_energy_threshold = True
            self._microphone = sr.Microphone()
            # Calibración rápida del ruido ambiente
            with self._microphone as source:
                self._recognizer.adjust_for_ambient_noise(source, duration=1)
        except Exception as e:
            raise RuntimeError(
                f"No se pudo inicializar el micrófono. "
                f"Asegúrate de tener PyAudio instalado: {e}"
            )

    def listen_once(self) -> Optional[str]:
        """
        Escucha una frase del micrófono y devuelve el texto reconocido.
        Retorna None si no se reconoce nada o hay error.
        """
        try:
            import speech_recognition as sr
            self._init()
            with self._microphone as source:
                audio = self._recognizer.listen(
                    source,
                    timeout=self._listen_timeout,
                    phrase_time_limit=self._phrase_time_limit,
                )
            text = self._recognizer.recognize_google(audio, language=self._language)
            return text.strip() if text else None
        except Exception:
            # WaitTimeoutError, UnknownValueError, RequestError, etc.
            return None

    def listen_for_wake_word(self, wake_word: str = WAKE_WORD) -> Optional[str]:
        """
        Escucha continuamente hasta detectar la wake word.
        Cuando la detecta, devuelve el resto del texto (el comando).
        Si la frase es solo la wake word, escucha otra vez para el comando.
        """
        text = self.listen_once()
        if text is None:
            return None
        text_lower = text.lower().strip()
        if wake_word not in text_lower:
            return None  # No dijo la wake word

        # Extraer el comando después de la wake word
        idx = text_lower.find(wake_word)
        command = text[idx + len(wake_word):].strip()
        # Limpiar puntuación al inicio
        command = command.lstrip(",. ")

        if command:
            return command

        # Si solo dijo "Jarvis", escuchar el comando
        return self.listen_once()

    def is_available(self) -> bool:
        """Comprueba si el micrófono está disponible."""
        try:
            import speech_recognition as sr
            mics = sr.Microphone.list_microphone_names()
            return len(mics) > 0
        except Exception:
            return False

    def list_microphones(self) -> list[str]:
        """Lista los micrófonos disponibles."""
        try:
            import speech_recognition as sr
            return sr.Microphone.list_microphone_names()
        except Exception:
            return []


# ---------------------------------------------------------------------------
# Utilidades
# ---------------------------------------------------------------------------

def _clean_for_speech(text: str) -> str:
    """Limpia texto de markdown y caracteres especiales para lectura natural."""
    # Eliminar bloques de código
    text = re.sub(r"```[\s\S]*?```", " código omitido ", text)
    text = re.sub(r"`([^`]+)`", r"\1", text)
    # Eliminar headers markdown
    text = re.sub(r"^#{1,6}\s+", "", text, flags=re.MULTILINE)
    # Eliminar bold/italic
    text = re.sub(r"\*\*([^*]+)\*\*", r"\1", text)
    text = re.sub(r"\*([^*]+)\*", r"\1", text)
    text = re.sub(r"__([^_]+)__", r"\1", text)
    text = re.sub(r"_([^_]+)_", r"\1", text)
    # Eliminar links markdown
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    # Eliminar listas markdown
    text = re.sub(r"^[\-\*]\s+", "", text, flags=re.MULTILINE)
    # Eliminar emojis y caracteres especiales
    text = re.sub(r"[⚙️🧹📝✓✗→←↑↓▶◀🔹🔸💡⚠️❌✅]", "", text)
    # Colapsar whitespace
    text = re.sub(r"\s+", " ", text)
    # Eliminar caracteres no pronunciables
    text = re.sub(r"[{}()\[\]|\\/<>~^]", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def speak_sentence_stream(speaker: VoiceSpeaker, text_buffer: str) -> str:
    """
    Dado un buffer de texto acumulado, detecta oraciones completas
    y las habla. Devuelve el texto restante (no hablado aún).

    Útil para streaming: vas acumulando tokens y cuando hay una oración
    completa, la habla inmediatamente.
    """
    # Patrones de fin de oración
    sentence_endings = re.compile(r"(?<=[.!?:;])\s")
    parts = sentence_endings.split(text_buffer)
    if len(parts) <= 1:
        # No hay oración completa aún
        return text_buffer
    # Hablar todas las oraciones completas menos la última (que está en progreso)
    for sentence in parts[:-1]:
        sentence = sentence.strip()
        if sentence:
            speaker.speak_async(sentence)
    return parts[-1]
