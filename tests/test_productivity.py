"""
Tests para JARVIS Productivity Module.
"""

import os
import sys
import json
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock
from datetime import datetime, timedelta

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from productivity import (
    set_reminder,
    set_timer,
    list_reminders,
    cancel_reminder,
    create_macro,
    run_macro,
    list_macros,
    delete_macro,
    generate_password,
    save_password,
    get_password,
    list_passwords,
    delete_password,
    _BUILTIN_MACROS,
    _load_json,
    _save_json,
)


@pytest.fixture
def tmp_jarvis_dir(tmp_path):
    """Redirige la persistencia a un directorio temporal."""
    import productivity
    original_dir = productivity._JARVIS_DIR
    original_reminders = productivity.REMINDERS_PATH
    original_macros = productivity.MACROS_PATH
    original_vault = productivity.VAULT_PATH

    productivity._JARVIS_DIR = tmp_path
    productivity.REMINDERS_PATH = tmp_path / "reminders.json"
    productivity.MACROS_PATH = tmp_path / "macros.json"
    productivity.VAULT_PATH = tmp_path / "vault.enc"

    yield tmp_path

    productivity._JARVIS_DIR = original_dir
    productivity.REMINDERS_PATH = original_reminders
    productivity.MACROS_PATH = original_macros
    productivity.VAULT_PATH = original_vault


# ---------------------------------------------------------------------------
# Reminders
# ---------------------------------------------------------------------------

class TestReminders:
    def test_set_reminder_minutes(self, tmp_jarvis_dir):
        result = set_reminder("Test reminder", minutes=5)
        data = json.loads(result)
        assert data["status"] == "ok"
        assert data["message"] == "Test reminder"
        assert data["in_minutes"] == 5

    def test_set_reminder_at_time(self, tmp_jarvis_dir):
        # Set for an hour from now
        future = (datetime.now() + timedelta(hours=1)).strftime("%H:%M")
        result = set_reminder("Meeting", at_time=future)
        data = json.loads(result)
        assert data["status"] == "ok"

    def test_set_reminder_invalid_time(self, tmp_jarvis_dir):
        result = set_reminder("Test", at_time="invalid")
        assert "Error" in result

    def test_set_reminder_empty_message(self):
        result = set_reminder("")
        assert "Error" in result

    def test_set_reminder_no_time(self):
        result = set_reminder("Test")
        assert "Error" in result

    def test_list_reminders_empty(self, tmp_jarvis_dir):
        result = list_reminders()
        data = json.loads(result)
        assert data["total_pending"] == 0

    def test_list_reminders_with_items(self, tmp_jarvis_dir):
        set_reminder("Reminder 1", minutes=10)
        set_reminder("Reminder 2", minutes=20)
        result = list_reminders()
        data = json.loads(result)
        assert data["total_pending"] == 2

    def test_cancel_reminder(self, tmp_jarvis_dir):
        result = set_reminder("Cancel me", minutes=10)
        data = json.loads(result)
        rid = data["id"]
        cancel_result = cancel_reminder(rid)
        assert "cancelado" in cancel_result.lower()

    def test_cancel_nonexistent(self, tmp_jarvis_dir):
        result = cancel_reminder("nonexistent_id")
        assert "Error" in result

    def test_set_timer(self, tmp_jarvis_dir):
        result = set_timer("Descanso", minutes=5)
        data = json.loads(result)
        assert data["status"] == "ok"
        assert "Timer" in data["message"]


# ---------------------------------------------------------------------------
# Macros
# ---------------------------------------------------------------------------

class TestMacros:
    def test_list_macros_builtins(self, tmp_jarvis_dir):
        result = list_macros()
        data = json.loads(result)
        names = [m["name"] for m in data["macros"]]
        assert "trabajo" in names
        assert "gaming" in names
        assert "estudio" in names

    def test_create_macro(self, tmp_jarvis_dir):
        steps = [
            {"action": "open_application", "args": {"app_name": "Chrome"}},
            {"action": "set_volume", "args": {"level": 50}},
        ]
        result = create_macro("mi_macro", steps, "Mi macro personalizada")
        data = json.loads(result)
        assert data["status"] == "ok"
        assert data["name"] == "mi_macro"
        assert data["steps_count"] == 2

    def test_create_macro_empty_name(self):
        result = create_macro("", [])
        assert "Error" in result

    def test_create_macro_invalid_action(self, tmp_jarvis_dir):
        steps = [{"action": "nonexistent_action", "args": {}}]
        result = create_macro("bad_macro", steps)
        assert "Error" in result

    def test_create_macro_builtin_override(self, tmp_jarvis_dir):
        result = create_macro("trabajo", [{"action": "open_application", "args": {"app_name": "Chrome"}}])
        assert "Error" in result
        assert "built-in" in result.lower()

    def test_delete_macro_requires_confirm(self, tmp_jarvis_dir):
        steps = [{"action": "open_application", "args": {"app_name": "Notepad"}}]
        create_macro("temp_macro", steps)
        result = delete_macro("temp_macro")
        assert "confirm" in result.lower()

    def test_delete_macro_with_confirm(self, tmp_jarvis_dir):
        steps = [{"action": "open_application", "args": {"app_name": "Notepad"}}]
        create_macro("temp_macro2", steps)
        result = delete_macro("temp_macro2", confirm=True)
        assert "eliminada" in result.lower()

    def test_delete_builtin_macro(self, tmp_jarvis_dir):
        result = delete_macro("trabajo", confirm=True)
        assert "Error" in result

    def test_run_macro(self, tmp_jarvis_dir):
        steps = [
            {"action": "set_volume", "args": {"level": 50}},
        ]
        create_macro("test_run", steps)
        with patch("productivity._MACRO_ACTION_MAP", {"set_volume": MagicMock(return_value="OK")}):
            result = run_macro("test_run")
            data = json.loads(result)
            assert data["macro"] == "test_run"
            assert data["steps_executed"] == 1

    def test_run_nonexistent_macro(self, tmp_jarvis_dir):
        result = run_macro("nonexistent")
        assert "Error" in result


# ---------------------------------------------------------------------------
# Passwords
# ---------------------------------------------------------------------------

class TestPasswords:
    def test_generate_password_default(self):
        result = generate_password()
        data = json.loads(result)
        assert len(data["password"]) == 16
        assert data["strength"] == "fuerte"

    def test_generate_password_custom(self):
        result = generate_password(length=24, count=3)
        data = json.loads(result)
        assert len(data["passwords"]) == 3
        assert all(len(p) == 24 for p in data["passwords"])

    def test_generate_password_no_special(self):
        result = generate_password(length=12, include_special=False)
        data = json.loads(result)
        pw = data["password"]
        assert len(pw) == 12
        assert all(c.isalnum() for c in pw)

    def test_generate_password_too_short(self):
        result = generate_password(length=3)
        assert "Error" in result

    def test_generate_password_too_long(self):
        result = generate_password(length=200)
        assert "Error" in result

    def test_save_password_no_vault_key(self, tmp_jarvis_dir):
        with patch.dict(os.environ, {"JARVIS_VAULT_KEY": ""}, clear=False):
            result = save_password("github", "user@test.com", "pass123")
            assert "Error" in result
            assert "VAULT_KEY" in result

    def test_save_and_get_password(self, tmp_jarvis_dir):
        with patch.dict(os.environ, {"JARVIS_VAULT_KEY": "test_master_key_123"}, clear=False):
            save_result = save_password("github", "user@test.com", "mypass123")
            data = json.loads(save_result)
            assert data["status"] == "ok"
            assert data["service"] == "github"

            get_result = get_password("github")
            get_data = json.loads(get_result)
            assert get_data["username"] == "user@test.com"
            assert get_data["password"] == "mypass123"

    def test_list_passwords(self, tmp_jarvis_dir):
        with patch.dict(os.environ, {"JARVIS_VAULT_KEY": "test_key_456"}, clear=False):
            save_password("google", "me@gmail.com", "pass1")
            save_password("netflix", "me@net.com", "pass2")
            result = list_passwords()
            data = json.loads(result)
            assert data["total"] == 2
            services = [s["service"] for s in data["services"]]
            assert "google" in services
            assert "netflix" in services
            # Passwords should NOT be shown
            for s in data["services"]:
                assert "password" not in s or "password_length" in s

    def test_delete_password(self, tmp_jarvis_dir):
        with patch.dict(os.environ, {"JARVIS_VAULT_KEY": "test_key_789"}, clear=False):
            save_password("temp_service", "user", "pass")
            # Without confirm
            result = delete_password("temp_service")
            assert "confirm" in result.lower()
            # With confirm
            result2 = delete_password("temp_service", confirm=True)
            assert "eliminadas" in result2.lower()

    def test_get_password_not_found(self, tmp_jarvis_dir):
        with patch.dict(os.environ, {"JARVIS_VAULT_KEY": "test_key_000"}, clear=False):
            result = get_password("nonexistent_service")
            assert "Error" in result
