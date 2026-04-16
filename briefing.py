"""
JARVIS Daily Briefing Module — Buenos días, señor.

Genera un resumen matutino personalizado con:
- Clima, noticias, recordatorios, estado del sistema, crypto, etc.
"""

import json
import os
from datetime import datetime
from typing import Optional


# ---------------------------------------------------------------------------
# Configuración
# ---------------------------------------------------------------------------

DEFAULT_CITY = os.environ.get("JARVIS_CITY", "Madrid")
BRIEFING_CRYPTO = os.environ.get("JARVIS_BRIEFING_CRYPTO", "bitcoin")


def daily_briefing(
    city: Optional[str] = None,
    include_crypto: bool = True,
    include_news: bool = True,
    include_system: bool = True,
) -> str:
    """
    Genera el briefing diario de JARVIS — un resumen completo del estado del día.
    Incluye: clima, noticias, recordatorios pendientes, estado del sistema y crypto.

    Args:
        city: Ciudad para el clima (por defecto usa JARVIS_CITY o 'Madrid').
        include_crypto: Si incluir precio de criptomonedas.
        include_news: Si incluir titulares de noticias.
        include_system: Si incluir estado del sistema (CPU, RAM, disco, batería).
    """
    try:
        city = city or DEFAULT_CITY
        now = datetime.now()
        hour = now.hour

        # Saludo según la hora
        if hour < 12:
            greeting = "Buenos días, señor"
        elif hour < 20:
            greeting = "Buenas tardes, señor"
        else:
            greeting = "Buenas noches, señor"

        sections = []
        sections.append(f"# 🌅 {greeting}")
        sections.append(f"📅 **{now.strftime('%A, %d de %B de %Y')}** — {now.strftime('%H:%M')}\n")

        # --- Clima ---
        try:
            from apis import get_weather
            weather_result = get_weather(city)
            try:
                w = json.loads(weather_result)
                if "error" not in str(w).lower():
                    temp = w.get("temperature", "?")
                    desc = w.get("description", w.get("weather", "?"))
                    humidity = w.get("humidity", "?")
                    sections.append(f"## 🌤️ Clima en {city}")
                    sections.append(f"- Temperatura: **{temp}°C**")
                    sections.append(f"- Condición: {desc}")
                    sections.append(f"- Humedad: {humidity}%\n")
                else:
                    sections.append(f"## 🌤️ Clima: no disponible\n")
            except (json.JSONDecodeError, TypeError):
                sections.append(f"## 🌤️ Clima: {weather_result[:100]}\n")
        except Exception:
            sections.append("## 🌤️ Clima: módulo no disponible\n")

        # --- Noticias ---
        if include_news:
            try:
                from apis import get_news
                news_result = get_news(query="", country="es", max_results=5)
                try:
                    news = json.loads(news_result)
                    articles = news.get("articles", [])
                    if articles:
                        sections.append("## 📰 Titulares")
                        for i, art in enumerate(articles[:5], 1):
                            title = art.get("title", "Sin título")
                            source = art.get("source", "")
                            sections.append(f"{i}. **{title}** — _{source}_")
                        sections.append("")
                except (json.JSONDecodeError, TypeError):
                    pass
            except Exception:
                pass

        # --- Recordatorios ---
        try:
            from productivity import list_reminders
            rem_result = list_reminders()
            try:
                rem = json.loads(rem_result)
                pending = rem.get("pending", [])
                if pending:
                    sections.append("## ⏰ Recordatorios pendientes")
                    for r in pending[:5]:
                        msg = r.get("message", "")
                        remaining = r.get("remaining_minutes", 0)
                        sections.append(f"- {msg} (en {remaining} min)")
                    sections.append("")
                else:
                    sections.append("## ⏰ No hay recordatorios pendientes\n")
            except (json.JSONDecodeError, TypeError):
                pass
        except Exception:
            pass

        # --- Sistema ---
        if include_system:
            try:
                from automation import system_info, get_battery
                sys_result = system_info()
                try:
                    si = json.loads(sys_result)
                    sections.append("## 💻 Estado del sistema")
                    sections.append(f"- CPU: **{si.get('cpu_percent', '?')}%**")
                    sections.append(f"- RAM: **{si.get('ram_percent', '?')}%** usada")
                    disk = si.get("disk_percent", si.get("disk_usage_percent", "?"))
                    sections.append(f"- Disco: **{disk}%** usado")
                except (json.JSONDecodeError, TypeError):
                    sections.append(f"## 💻 Sistema: {sys_result[:100]}")

                bat_result = get_battery()
                try:
                    bat = json.loads(bat_result)
                    pct = bat.get("percent", "?")
                    plugged = bat.get("plugged", False)
                    status = "🔌 conectado" if plugged else "🔋 batería"
                    sections.append(f"- Batería: **{pct}%** ({status})")
                except (json.JSONDecodeError, TypeError):
                    pass
                sections.append("")
            except Exception:
                pass

        # --- Crypto ---
        if include_crypto:
            try:
                from apis import get_crypto_price
                crypto_result = get_crypto_price(BRIEFING_CRYPTO)
                try:
                    cr = json.loads(crypto_result)
                    price = cr.get("price_usd", cr.get("price", "?"))
                    change = cr.get("change_24h", "?")
                    sections.append(f"## 📈 Crypto ({BRIEFING_CRYPTO.upper()})")
                    sections.append(f"- Precio: **${price}**")
                    sections.append(f"- Cambio 24h: {change}%\n")
                except (json.JSONDecodeError, TypeError):
                    pass
            except Exception:
                pass

        # --- Agentes activos ---
        try:
            from agents import list_running_agents
            agents_result = list_running_agents()
            try:
                ag = json.loads(agents_result)
                count = ag.get("active_count", 0)
                if count > 0:
                    sections.append(f"## 🤖 Agentes activos: {count}")
                    for a in ag.get("agents", []):
                        sections.append(f"- **{a.get('name')}**: {a.get('task', '')}")
                    sections.append("")
            except (json.JSONDecodeError, TypeError):
                pass
        except Exception:
            pass

        # Cierre
        sections.append("---")
        sections.append("_¿En qué puedo ayudarle hoy?_")

        briefing_text = "\n".join(sections)

        return json.dumps({
            "status": "ok",
            "briefing": briefing_text,
            "city": city,
            "timestamp": now.isoformat(timespec="seconds"),
        }, ensure_ascii=False)

    except Exception as e:
        return f"Error en daily_briefing: {e}"


def quick_status() -> str:
    """
    Devuelve un resumen rápido de una línea del estado actual del sistema.
    Útil como respuesta a '¿cómo estamos?' o 'estado rápido'.
    """
    try:
        parts = []

        try:
            import psutil
            cpu = psutil.cpu_percent(interval=0.5)
            ram = psutil.virtual_memory().percent
            parts.append(f"CPU {cpu}%")
            parts.append(f"RAM {ram}%")
        except Exception:
            pass

        try:
            from productivity import list_reminders
            rem = json.loads(list_reminders())
            pending = rem.get("total_pending", 0)
            if pending:
                parts.append(f"{pending} recordatorio(s)")
        except Exception:
            pass

        try:
            from agents import list_running_agents
            ag = json.loads(list_running_agents())
            active = ag.get("active_count", 0)
            if active:
                parts.append(f"{active} agente(s) activo(s)")
        except Exception:
            pass

        now = datetime.now().strftime("%H:%M")
        summary = " | ".join(parts) if parts else "Todo en orden"

        return json.dumps({
            "status": "ok",
            "time": now,
            "summary": summary,
        }, ensure_ascii=False)
    except Exception as e:
        return f"Error en quick_status: {e}"
