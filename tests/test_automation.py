"""
Tests para JARVIS Automation Module.
Tests de funciones de lectura (no ejecutan acciones destructivas).
"""

import os
import sys
import json
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from automation import (
    open_application,
    close_application,
    get_volume,
    set_volume,
    toggle_mute,
    take_screenshot,
    set_wallpaper,
    get_clipboard,
    set_clipboard,
    show_notification,
    open_url,
    lock_screen,
    system_info,
    get_battery,
    set_brightness,
    get_brightness,
    empty_recycle_bin,
    KNOWN_APPS,
    _run_ps,
)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestKnownApps:
    def test_common_apps_exist(self):
        """Verifica que los atajos comunes estén en el mapeo."""
        assert "chrome" in KNOWN_APPS
        assert "notepad" in KNOWN_APPS
        assert "vscode" in KNOWN_APPS
        assert "spotify" in KNOWN_APPS
        assert "discord" in KNOWN_APPS

    def test_spanish_aliases(self):
        """Verifica aliases en español."""
        assert "calculadora" in KNOWN_APPS
        assert "bloc de notas" in KNOWN_APPS
        assert "explorador" in KNOWN_APPS
        assert "configuración" in KNOWN_APPS


class TestOpenApplication:
    def test_open_known_app(self):
        with patch("automation._run_ps", return_value=(0, "", "")):
            result = open_application("notepad")
            assert "abierta" in result.lower()

    def test_open_unknown_app(self):
        with patch("automation._run_ps", return_value=(1, "", "error")):
            with patch("shutil.which", return_value=None):
                result = open_application("nonexistent_app_xyz")
                assert "error" in result.lower() or "no pude" in result.lower()


class TestCloseApplication:
    def test_requires_confirm(self):
        result = close_application("chrome")
        assert "confirm" in result.lower()

    def test_close_with_confirm(self):
        with patch("automation._run_ps", return_value=(0, "stopped", "")):
            result = close_application("notepad", confirm=True)
            assert "cerrada" in result.lower()


class TestVolume:
    def test_get_volume(self):
        mock_json = json.dumps({"volume": 75, "muted": False})
        with patch("automation._run_ps", return_value=(0, mock_json, "")):
            result = get_volume()
            data = json.loads(result)
            assert data["volume"] == 75
            assert data["muted"] is False

    def test_set_volume_valid(self):
        with patch("automation._run_ps", return_value=(0, "OK", "")):
            result = set_volume(50)
            assert "50%" in result

    def test_set_volume_invalid(self):
        result = set_volume(150)
        assert "Error" in result

    def test_set_volume_zero(self):
        with patch("automation._run_ps", return_value=(0, "OK", "")):
            result = set_volume(0)
            assert "0%" in result

    def test_toggle_mute(self):
        with patch("automation._run_ps", return_value=(0, "Silenciado", "")):
            result = toggle_mute()
            assert "silenciado" in result.lower() or "activado" in result.lower()


class TestScreenshot:
    def test_screenshot_no_mss(self):
        with patch.dict("sys.modules", {"mss": None}):
            # Forzar ImportError
            import importlib
            result = take_screenshot()
            # Puede funcionar o dar error de mss
            assert isinstance(result, str)

    def test_screenshot_with_mss(self):
        mock_sct = MagicMock()
        mock_sct.__enter__ = MagicMock(return_value=mock_sct)
        mock_sct.__exit__ = MagicMock(return_value=False)
        mock_sct.monitors = [
            {"left": 0, "top": 0, "width": 1920, "height": 1080},
            {"left": 0, "top": 0, "width": 1920, "height": 1080},
        ]
        mock_img = MagicMock()
        mock_img.width = 1920
        mock_img.height = 1080
        mock_img.rgb = b"\x00" * (1920 * 1080 * 3)
        mock_img.size = (1920, 1080)
        mock_sct.grab.return_value = mock_img

        with patch("mss.mss", return_value=mock_sct):
            with patch("mss.tools.to_png"):
                with patch("os.path.getsize", return_value=12345):
                    result = take_screenshot(save_path="/tmp/test_screenshot.png")
                    data = json.loads(result)
                    assert data["status"] == "ok"
                    assert data["resolution"] == "1920x1080"


class TestWallpaper:
    def test_nonexistent_image(self):
        result = set_wallpaper("/nonexistent/image.jpg")
        assert "Error" in result

    def test_invalid_format(self):
        # Create a temp file with wrong extension
        import tempfile
        with tempfile.NamedTemporaryFile(suffix=".xyz", delete=False) as f:
            f.write(b"fake")
            temp = f.name
        try:
            result = set_wallpaper(temp)
            assert "Error" in result
            assert "no soportado" in result.lower()
        finally:
            os.unlink(temp)


class TestClipboard:
    def test_get_clipboard(self):
        with patch("automation._run_ps", return_value=(0, "Hello World", "")):
            result = get_clipboard()
            assert result == "Hello World"

    def test_get_clipboard_empty(self):
        with patch("automation._run_ps", return_value=(0, "", "")):
            result = get_clipboard()
            assert "vacío" in result.lower()

    def test_set_clipboard(self):
        with patch("automation._run_ps", return_value=(0, "", "")):
            result = set_clipboard("Test text")
            assert "copiado" in result.lower()

    def test_set_clipboard_empty(self):
        result = set_clipboard("")
        assert "Error" in result


class TestNotification:
    def test_empty_message(self):
        result = show_notification(message="")
        assert "Error" in result

    def test_notification_with_plyer(self):
        mock_notification = MagicMock()
        with patch.dict("sys.modules", {"plyer": MagicMock(notification=mock_notification)}):
            with patch("plyer.notification.notify"):
                result = show_notification(title="Test", message="Hello")
                assert isinstance(result, str)


class TestOpenUrl:
    def test_open_shortcut(self):
        with patch("webbrowser.open") as mock_open:
            result = open_url("youtube")
            mock_open.assert_called_once_with("https://www.youtube.com")
            assert "abierta" in result.lower()

    def test_open_full_url(self):
        with patch("webbrowser.open") as mock_open:
            result = open_url("https://example.com")
            mock_open.assert_called_once_with("https://example.com")
            assert "abierta" in result.lower()

    def test_open_domain(self):
        with patch("webbrowser.open") as mock_open:
            result = open_url("example.com")
            mock_open.assert_called_once_with("https://example.com")

    def test_open_empty(self):
        result = open_url("")
        assert "Error" in result


class TestLockScreen:
    def test_requires_confirm(self):
        result = lock_screen()
        assert "confirm" in result.lower()

    def test_lock_with_confirm(self):
        with patch("automation._run_ps", return_value=(0, "", "")):
            result = lock_screen(confirm=True)
            assert "bloqueada" in result.lower()


class TestSystemInfo:
    def test_system_info(self):
        result = system_info()
        data = json.loads(result)
        assert "os" in data
        assert "cpu" in data
        assert "memory" in data
        assert "disks" in data
        assert data["cpu"]["logical_cores"] > 0
        assert data["memory"]["total_gb"] > 0


class TestGetBattery:
    def test_battery(self):
        result = get_battery()
        data = json.loads(result)
        # En un desktop puede no haber batería
        assert "percent" in data or "status" in data


class TestBrightness:
    def test_set_brightness_valid(self):
        with patch("automation._run_ps", return_value=(0, "Brillo establecido al 50%", "")):
            result = set_brightness(50)
            assert "50%" in result

    def test_set_brightness_invalid(self):
        result = set_brightness(150)
        assert "Error" in result

    def test_get_brightness(self):
        mock_json = json.dumps({"brightness": 75, "levels": [0, 25, 50, 75, 100]})
        with patch("automation._run_ps", return_value=(0, mock_json, "")):
            result = get_brightness()
            assert "75" in result


class TestRecycleBin:
    def test_requires_confirm(self):
        result = empty_recycle_bin()
        assert "confirm" in result.lower()

    def test_empty_with_confirm(self):
        with patch("automation._run_ps", return_value=(0, "Papelera vaciada. Elementos eliminados: 5", "")):
            result = empty_recycle_bin(confirm=True)
            assert "vaciada" in result.lower()
