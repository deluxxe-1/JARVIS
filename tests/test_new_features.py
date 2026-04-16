"""
Tests para los 6 nuevos módulos de JARVIS:
hotkey, clipboard_intel, briefing, network, media, organizer.
"""

import os
import sys
import json
from pathlib import Path
from unittest.mock import patch, MagicMock
from datetime import datetime

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


# ============================================================================
# Hotkey
# ============================================================================

from hotkey import get_hotkey_status, change_hotkey

class TestHotkey:
    def test_get_status(self):
        result = get_hotkey_status()
        data = json.loads(result)
        assert "active" in data
        assert "combo" in data

    def test_change_hotkey(self):
        original = "win+j"
        result = change_hotkey("ctrl+shift+j")
        assert "ctrl+shift+j" in result.lower()
        # Restaurar
        change_hotkey(original)

    def test_change_hotkey_empty(self):
        result = change_hotkey("")
        assert "Error" in result


# ============================================================================
# Clipboard Intelligence
# ============================================================================

from clipboard_intel import _detect_content_type, _suggest_actions

class TestClipboardDetect:
    def test_detect_url(self):
        result = _detect_content_type("https://www.google.com")
        assert result["type"] == "url"

    def test_detect_email(self):
        result = _detect_content_type("user@example.com")
        assert result["type"] == "email"

    def test_detect_json(self):
        result = _detect_content_type('{"key": "value", "number": 42}')
        assert result["type"] == "json"
        assert result["parsed"] is True

    def test_detect_code_python(self):
        code = "import os\ndef hello():\n    return 'world'\n"
        result = _detect_content_type(code)
        assert result["type"] == "code"
        assert result["language"] == "Python"

    def test_detect_code_js(self):
        code = "const x = 5;\nfunction hello() {\n  return x;\n}\n"
        result = _detect_content_type(code)
        assert result["type"] == "code"
        assert result["language"] == "JavaScript"

    def test_detect_ip(self):
        result = _detect_content_type("192.168.1.100")
        assert result["type"] == "ip_address"

    def test_detect_long_text(self):
        text = "palabra " * 150
        result = _detect_content_type(text)
        assert result["type"] == "long_text"

    def test_detect_short_text(self):
        result = _detect_content_type("hola mundo")
        assert result["type"] == "short_text"

    def test_detect_empty(self):
        result = _detect_content_type("")
        assert result["type"] == "empty"

    def test_suggest_actions_url(self):
        ct = {"type": "url"}
        actions = _suggest_actions(ct)
        assert len(actions) > 0
        assert any("abrir" in a.lower() or "open" in a.lower() for a in actions)

    def test_suggest_actions_code(self):
        ct = {"type": "code"}
        actions = _suggest_actions(ct)
        assert len(actions) > 0


# ============================================================================
# Briefing
# ============================================================================

from briefing import daily_briefing, quick_status

class TestBriefing:
    def test_daily_briefing_structure(self):
        # Mock the modules that briefing imports lazily
        mock_apis = MagicMock()
        mock_apis.get_weather.return_value = '{"temperature": 22, "description": "Soleado", "humidity": 45}'
        mock_apis.get_news.return_value = '{"articles": [{"title": "Test News", "source": "Test"}]}'
        mock_apis.get_crypto_price.return_value = '{"price_usd": 65000, "change_24h": 2.3}'

        mock_prod = MagicMock()
        mock_prod.list_reminders.return_value = '{"pending": [], "completed": [], "total_pending": 0}'

        mock_auto = MagicMock()
        mock_auto.system_info.return_value = '{"cpu_percent": 25, "ram_percent": 60, "disk_percent": 45}'
        mock_auto.get_battery.return_value = '{"percent": 85, "plugged": true}'

        mock_agents = MagicMock()
        mock_agents.list_running_agents.return_value = '{"active_count": 0, "agents": []}'

        with patch.dict("sys.modules", {
            "apis": mock_apis,
            "productivity": mock_prod,
            "automation": mock_auto,
            "agents": mock_agents,
        }):
            result = daily_briefing("Madrid")
            data = json.loads(result)
            assert data["status"] == "ok"
            assert "briefing" in data

    def test_quick_status(self):
        result = quick_status()
        data = json.loads(result)
        assert data["status"] == "ok"
        assert "summary" in data


# ============================================================================
# Network
# ============================================================================

from network import ping_host, scan_ports, check_internet, _parse_ports, _parse_ping_stats

class TestNetwork:
    def test_parse_ports_simple(self):
        ports = _parse_ports("80,443,8080")
        assert ports == [80, 443, 8080]

    def test_parse_ports_range(self):
        ports = _parse_ports("80-85")
        assert ports == [80, 81, 82, 83, 84, 85]

    def test_parse_ports_mixed(self):
        ports = _parse_ports("22,80-82,443")
        assert ports == [22, 80, 81, 82, 443]

    def test_parse_ports_invalid(self):
        ports = _parse_ports("abc,xyz")
        assert ports == []

    def test_parse_ping_stats_linux(self):
        output = "rtt min/avg/max/mdev = 1.234/2.345/3.456/0.567 ms"
        stats = _parse_ping_stats(output)
        assert stats["avg_ms"] == 2.345

    def test_parse_ping_stats_loss(self):
        output = "3 packets transmitted, 2 received, 33% packet loss"
        stats = _parse_ping_stats(output)
        assert stats["packet_loss_pct"] == 33

    def test_ping_empty_host(self):
        result = ping_host("")
        assert "Error" in result

    def test_scan_ports_empty_host(self):
        result = scan_ports("")
        assert "Error" in result

    def test_check_internet(self):
        result = check_internet(timeout=2.0)
        data = json.loads(result)
        assert data["status"] == "ok"
        assert "connected" in data


# ============================================================================
# Media
# ============================================================================

from media import media_play_pause, media_next, media_previous, media_stop

class TestMedia:
    @patch("media._send_media_key", return_value="ok")
    def test_play_pause(self, mock_key):
        result = media_play_pause()
        data = json.loads(result)
        assert data["status"] == "ok"
        assert data["action"] == "play_pause"

    @patch("media._send_media_key", return_value="ok")
    def test_next(self, mock_key):
        result = media_next()
        data = json.loads(result)
        assert data["status"] == "ok"
        assert data["action"] == "next_track"

    @patch("media._send_media_key", return_value="ok")
    def test_previous(self, mock_key):
        result = media_previous()
        data = json.loads(result)
        assert data["status"] == "ok"

    @patch("media._send_media_key", return_value="ok")
    def test_stop(self, mock_key):
        result = media_stop()
        data = json.loads(result)
        assert data["status"] == "ok"


# ============================================================================
# Organizer
# ============================================================================

from organizer import organize_folder, find_duplicates, clean_old_files, folder_stats, _get_category

class TestOrganizer:
    def test_get_category(self):
        assert _get_category("document.pdf") == "Documentos"
        assert _get_category("photo.jpg") == "Imagenes"
        assert _get_category("video.mp4") == "Videos"
        assert _get_category("song.mp3") == "Musica"
        assert _get_category("script.py") == "Codigo"
        assert _get_category("archive.zip") == "Comprimidos"
        assert _get_category("setup.exe") == "Instaladores"
        assert _get_category("readme.txt") == "Texto"
        assert _get_category("unknown.xyz") == "Otros"

    def test_organize_dry_run(self, tmp_path):
        (tmp_path / "doc.pdf").write_text("pdf content")
        (tmp_path / "pic.jpg").write_bytes(b"jpg")
        (tmp_path / "code.py").write_text("print('hi')")

        result = organize_folder(str(tmp_path), dry_run=True)
        data = json.loads(result)
        assert data["status"] == "ok"
        assert data["mode"] == "dry_run"
        assert data["total_files"] == 3
        assert "Documentos" in data["categories"]

    def test_organize_execute(self, tmp_path):
        (tmp_path / "doc.pdf").write_text("pdf content")
        (tmp_path / "pic.jpg").write_bytes(b"jpg")

        result = organize_folder(str(tmp_path), dry_run=False)
        data = json.loads(result)
        assert data["status"] == "ok"
        assert data["mode"] == "executed"
        assert data["files_moved"] == 2
        assert (tmp_path / "Documentos" / "doc.pdf").is_file()
        assert (tmp_path / "Imagenes" / "pic.jpg").is_file()

    def test_organize_nonexistent(self):
        result = organize_folder("/nonexistent/dir")
        assert "Error" in result

    def test_organize_empty_folder(self, tmp_path):
        result = organize_folder(str(tmp_path), dry_run=True)
        data = json.loads(result)
        assert "No hay archivos" in data.get("message", "")

    def test_find_duplicates(self, tmp_path):
        # Create duplicate files
        content = b"same content here" * 100
        (tmp_path / "file1.txt").write_bytes(content)
        (tmp_path / "file2.txt").write_bytes(content)
        (tmp_path / "unique.txt").write_bytes(b"different content")

        result = find_duplicates(str(tmp_path), min_size_kb=0)
        data = json.loads(result)
        assert data["status"] == "ok"
        assert data["duplicate_groups"] >= 1

    def test_find_duplicates_no_dupes(self, tmp_path):
        (tmp_path / "a.txt").write_bytes(b"aaa" * 500)
        (tmp_path / "b.txt").write_bytes(b"bbb" * 500)

        result = find_duplicates(str(tmp_path), min_size_kb=0)
        data = json.loads(result)
        assert data["duplicate_groups"] == 0

    def test_clean_old_files_dry_run(self, tmp_path):
        f = tmp_path / "old_file.log"
        f.write_text("old data")
        # Make it look old
        import time
        old_time = time.time() - (60 * 86400)  # 60 days ago
        os.utime(str(f), (old_time, old_time))

        result = clean_old_files(str(tmp_path), days=30, dry_run=True)
        data = json.loads(result)
        assert data["mode"] == "dry_run"
        assert data["files_to_delete"] >= 1

    def test_folder_stats(self, tmp_path):
        (tmp_path / "doc.pdf").write_text("pdf")
        (tmp_path / "img.png").write_bytes(b"png")
        (tmp_path / "code.py").write_text("code")

        result = folder_stats(str(tmp_path))
        data = json.loads(result)
        assert data["status"] == "ok"
        assert data["total_files"] == 3
        assert "categories" in data
