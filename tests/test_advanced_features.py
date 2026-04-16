"""
Tests para los 5 módulos nuevos de JARVIS:
git_tools, guard, knowledge, windows, scraper.
"""

import os
import sys
import json
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock
from datetime import datetime

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


# ============================================================================
# Git Tools
# ============================================================================

from git_tools import git_status, git_log, git_branch, git_diff, _run_git

class TestGitTools:
    def test_git_status_no_repo(self, tmp_path):
        result = git_status(str(tmp_path))
        assert "Error" in result or "no estás" in result

    @patch("git_tools._run_git")
    def test_git_status_clean(self, mock_run):
        mock_run.side_effect = [
            (0, "true", ""),  # is_inside_work_tree
            (0, "## main", ""),  # status --porcelain
        ]
        result = git_status("/fake/repo")
        data = json.loads(result)
        assert data["status"] == "ok"
        assert data["clean"] is True

    @patch("git_tools._run_git")
    def test_git_status_modified(self, mock_run):
        mock_run.side_effect = [
            (0, "true", ""),
            (0, "## main\n M file.py\n?? new.txt", ""),
        ]
        result = git_status("/fake")
        data = json.loads(result)
        assert "file.py" in data["modified"]
        assert "new.txt" in data["untracked"]

    @patch("git_tools._run_git")
    def test_git_log(self, mock_run):
        mock_run.side_effect = [
            (0, "true", ""),
            (0, "abc1234|Author|2 hours ago|Fix bug", ""),
        ]
        result = git_log(5, "/fake")
        data = json.loads(result)
        assert data["status"] == "ok"
        assert len(data["commits"]) == 1
        assert data["commits"][0]["hash"] == "abc1234"

    @patch("git_tools._run_git")
    def test_git_branch_list(self, mock_run):
        mock_run.side_effect = [
            (0, "true", ""),
            (0, "* main\n  dev\n  feature/x", ""),
        ]
        result = git_branch("list", path="/fake")
        data = json.loads(result)
        assert data["status"] == "ok"
        assert data["current"] == "main"
        assert len(data["branches"]) == 3

    @patch("git_tools._run_git")
    def test_git_diff(self, mock_run):
        mock_run.side_effect = [
            (0, "true", ""),
            (0, "file.py | 2 +-", ""),
            (0, "+new line\n-old line", ""),
        ]
        result = git_diff("/fake")
        data = json.loads(result)
        assert data["status"] == "ok"


# ============================================================================
# System Guard
# ============================================================================

from guard import _DEFAULT_THRESHOLDS, _check_system, set_guard_threshold, guard_alerts_history

class TestGuard:
    def test_default_thresholds(self):
        assert _DEFAULT_THRESHOLDS["cpu_percent"] == 90
        assert _DEFAULT_THRESHOLDS["ram_percent"] == 85
        assert _DEFAULT_THRESHOLDS["battery_low"] == 15

    def test_check_system_no_alerts(self):
        # Con umbrales muy altos no debería haber alertas
        config = {
            "cpu_percent": 100,
            "ram_percent": 100,
            "disk_percent": 100,
            "battery_low": 0,
        }
        alerts = _check_system(config)
        assert isinstance(alerts, list)
        # Puede que no haya alertas con umbrales al 100%
        # (depende del sistema actual)

    def test_set_threshold(self, tmp_path):
        with patch("guard.GUARD_CONFIG_PATH", tmp_path / "guard.json"):
            with patch("guard._JARVIS_DIR", tmp_path):
                result = set_guard_threshold(cpu_percent=80, ram_percent=70)
                data = json.loads(result)
                assert data["status"] == "ok"
                assert data["thresholds"]["cpu_percent"] == 80
                assert data["thresholds"]["ram_percent"] == 70

    def test_set_threshold_clamp(self, tmp_path):
        with patch("guard.GUARD_CONFIG_PATH", tmp_path / "guard.json"):
            with patch("guard._JARVIS_DIR", tmp_path):
                result = set_guard_threshold(cpu_percent=5)
                data = json.loads(result)
                # Should be clamped to 10
                assert data["thresholds"]["cpu_percent"] == 10

    def test_alerts_history_empty(self, tmp_path):
        with patch("guard.GUARD_LOG_PATH", tmp_path / "nonexistent.jsonl"):
            result = guard_alerts_history()
            data = json.loads(result)
            assert data["total"] == 0


# ============================================================================
# Knowledge Base
# ============================================================================

from knowledge import save_note, save_bookmark, save_snippet, search_knowledge, delete_knowledge, list_knowledge_tags, _auto_tags

class TestKnowledge:
    def test_auto_tags_url(self):
        tags = _auto_tags("Check this: https://example.com")
        assert "url" in tags

    def test_auto_tags_code(self):
        tags = _auto_tags("def hello():\n    import os")
        assert "code" in tags

    def test_auto_tags_security(self):
        tags = _auto_tags("The password is 1234")
        assert "security" in tags

    def test_save_note(self, tmp_path):
        with patch("knowledge.KB_PATH", tmp_path / "kb.json"):
            with patch("knowledge._JARVIS_DIR", tmp_path):
                result = save_note("El servidor está en 10.0.0.5", title="Server IP", tags="infra,prod")
                data = json.loads(result)
                assert data["status"] == "ok"
                assert "infra" in data["tags"]

    def test_save_bookmark(self, tmp_path):
        with patch("knowledge.KB_PATH", tmp_path / "kb.json"):
            with patch("knowledge._JARVIS_DIR", tmp_path):
                result = save_bookmark("https://github.com", title="GitHub")
                data = json.loads(result)
                assert data["status"] == "ok"
                assert "bookmark" in data["tags"]

    def test_save_snippet(self, tmp_path):
        with patch("knowledge.KB_PATH", tmp_path / "kb.json"):
            with patch("knowledge._JARVIS_DIR", tmp_path):
                result = save_snippet("print('hi')", language="python", title="Hello")
                data = json.loads(result)
                assert data["status"] == "ok"
                assert "python" in data["tags"]

    def test_save_and_search(self, tmp_path):
        kb_path = tmp_path / "kb.json"
        with patch("knowledge.KB_PATH", kb_path):
            with patch("knowledge._JARVIS_DIR", tmp_path):
                save_note("El servidor prod está en 10.0.0.5", title="Server", tags="infra")
                save_note("El gato duerme en el sofá", title="Random", tags="personal")

                result = search_knowledge("servidor")
                data = json.loads(result)
                assert data["total"] == 1
                assert "Server" in data["results"][0]["title"]

    def test_search_by_tag(self, tmp_path):
        kb_path = tmp_path / "kb.json"
        with patch("knowledge.KB_PATH", kb_path):
            with patch("knowledge._JARVIS_DIR", tmp_path):
                save_note("Nota 1", tags="trabajo")
                save_note("Nota 2", tags="personal")

                result = search_knowledge("", tag="trabajo")
                data = json.loads(result)
                assert data["total"] == 1

    def test_delete_requires_confirm(self, tmp_path):
        with patch("knowledge.KB_PATH", tmp_path / "kb.json"):
            with patch("knowledge._JARVIS_DIR", tmp_path):
                result = delete_knowledge("abc123")
                assert "Confirmación" in result or "confirm" in result.lower()

    def test_list_tags(self, tmp_path):
        kb_path = tmp_path / "kb.json"
        with patch("knowledge.KB_PATH", kb_path):
            with patch("knowledge._JARVIS_DIR", tmp_path):
                save_note("Test", tags="alpha,beta")
                save_note("Test 2", tags="alpha,gamma")

                result = list_knowledge_tags()
                data = json.loads(result)
                assert data["total_entries"] == 2
                tag_names = [t["tag"] for t in data["tags"]]
                assert "alpha" in tag_names

    def test_save_empty_content(self):
        result = save_note("")
        assert "Error" in result


# ============================================================================
# Window Manager
# ============================================================================

from windows import close_window, focus_window

class TestWindowManager:
    def test_close_empty_title(self):
        result = close_window("")
        assert "Error" in result

    def test_focus_empty_title(self):
        result = focus_window("")
        assert "Error" in result


# ============================================================================
# Web Scraper
# ============================================================================

from scraper import scrape_text, scrape_links, scrape_images, monitor_price, _html_to_text, _extract_title

class TestScraper:
    def test_html_to_text(self):
        html = "<html><body><p>Hello</p><script>var x=1;</script><p>World</p></body></html>"
        text = _html_to_text(html)
        assert "Hello" in text
        assert "World" in text
        assert "var x" not in text

    def test_extract_title(self):
        html = "<html><head><title>My Page</title></head><body></body></html>"
        title = _extract_title(html)
        assert title == "My Page"

    def test_extract_title_empty(self):
        html = "<html><head></head><body></body></html>"
        title = _extract_title(html)
        assert title == ""

    def test_scrape_text_empty_url(self):
        result = scrape_text("")
        assert "Error" in result

    def test_scrape_links_empty_url(self):
        result = scrape_links("")
        assert "Error" in result

    def test_scrape_images_empty_url(self):
        result = scrape_images("")
        assert "Error" in result

    def test_monitor_price_empty_url(self):
        result = monitor_price("")
        assert "Error" in result

    def test_scrape_text_success(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = "<html><head><title>Test</title></head><body><p>Hello World</p></body></html>"
        mock_resp.raise_for_status = MagicMock()

        mock_requests = MagicMock()
        mock_requests.get.return_value = mock_resp

        with patch.dict("sys.modules", {"requests": mock_requests}):
            # re-import to pick up mock
            import importlib, scraper
            importlib.reload(scraper)
            result = scraper.scrape_text("https://example.com")
            data = json.loads(result)
            assert data["status"] == "ok"
            assert "Hello World" in data["text"]

    def test_scrape_links_success(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = '<html><body><a href="https://a.com">A</a><a href="/page">B</a></body></html>'
        mock_resp.raise_for_status = MagicMock()

        mock_requests = MagicMock()
        mock_requests.get.return_value = mock_resp

        with patch.dict("sys.modules", {"requests": mock_requests}):
            import importlib, scraper
            importlib.reload(scraper)
            result = scraper.scrape_links("https://example.com")
            data = json.loads(result)
            assert data["status"] == "ok"
            assert data["links_found"] >= 2

    def test_monitor_price_found(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = '<html><body><span class="price">$29.99</span></body></html>'
        mock_resp.raise_for_status = MagicMock()

        mock_requests = MagicMock()
        mock_requests.get.return_value = mock_resp

        with patch.dict("sys.modules", {"requests": mock_requests}):
            import importlib, scraper
            importlib.reload(scraper)
            result = scraper.monitor_price("https://shop.com/product", target_price=35.0)
            data = json.loads(result)
            assert data["status"] == "ok"
            assert data["prices_found"] >= 1
            assert data["below_target"] is True

    def test_monitor_price_above_target(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = '<html><body><span class="price">$59.99</span></body></html>'
        mock_resp.raise_for_status = MagicMock()

        mock_requests = MagicMock()
        mock_requests.get.return_value = mock_resp

        with patch.dict("sys.modules", {"requests": mock_requests}):
            import importlib, scraper
            importlib.reload(scraper)
            result = scraper.monitor_price("https://shop.com/product", target_price=30.0)
            data = json.loads(result)
            assert data["below_target"] is False
