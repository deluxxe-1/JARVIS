"""Tests para aaris.http_server (seguridad de bind y rate limit)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from aaris.http_server import _bind_requires_mandatory_token, _SlidingWindowLimiter


def test_loopback_no_mandatory_token():
    assert _bind_requires_mandatory_token("127.0.0.1") is False
    assert _bind_requires_mandatory_token("localhost") is False
    assert _bind_requires_mandatory_token("::1") is False


def test_non_loopback_requires_token():
    assert _bind_requires_mandatory_token("0.0.0.0") is True
    assert _bind_requires_mandatory_token("192.168.1.10") is True
    assert _bind_requires_mandatory_token("") is True


def test_rate_limiter():
    lim = _SlidingWindowLimiter(max_per_window=3, window_sec=60.0)
    assert lim.allow("a") is True
    assert lim.allow("a") is True
    assert lim.allow("a") is True
    assert lim.allow("a") is False
    assert lim.allow("b") is True
