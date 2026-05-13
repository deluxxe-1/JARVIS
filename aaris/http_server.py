from __future__ import annotations

import json
import os
import time
from collections import defaultdict
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Callable, Optional


def _bind_requires_mandatory_token(host: str) -> bool:
    """Solo escucha sin token en loopback explícito."""
    h = (host or "").strip().lower()
    return h not in ("127.0.0.1", "localhost", "::1")


class _SlidingWindowLimiter:
    """Límite simple por IP: N peticiones por ventana de 60 s."""

    def __init__(self, max_per_window: int, window_sec: float = 60.0) -> None:
        self.max_per_window = max(1, max_per_window)
        self.window_sec = window_sec
        self._hits: dict[str, list[float]] = defaultdict(list)

    def allow(self, key: str) -> bool:
        now = time.monotonic()
        bucket = self._hits[key]
        cutoff = now - self.window_sec
        while bucket and bucket[0] < cutoff:
            bucket.pop(0)
        if len(bucket) >= self.max_per_window:
            return False
        bucket.append(now)
        return True


def start_server(
    reply_fn: Callable[[str], str],
    *,
    host: str = "127.0.0.1",
    port: int = 8080,
    api_token: Optional[str] = None,
    max_body_bytes: int = 1024 * 1024,
) -> None:
    api_token = (api_token or "").strip()

    env_host = os.environ.get("AARIS_HTTP_HOST", "").strip()
    env_port = os.environ.get("AARIS_HTTP_PORT", "").strip()
    if env_host:
        host = env_host
    if env_port:
        try:
            port = int(env_port)
        except ValueError:
            pass

    if _bind_requires_mandatory_token(host) and not api_token:
        raise RuntimeError(
            "El servidor HTTP no está en solo localhost: defina AARIS_API_TOKEN antes de arrancar "
            "(obligatorio si escucha en 0.0.0.0, :: o una IP de red). Ej.: set AARIS_API_TOKEN=un_secreto_largo"
        )

    max_rpm = int(os.environ.get("AARIS_HTTP_MAX_REQ_PER_MIN", "48"))
    limiter = _SlidingWindowLimiter(max_per_window=max_rpm, window_sec=60.0)

    def _json(handler: BaseHTTPRequestHandler, status: int, payload: dict) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        handler.send_response(status)
        handler.send_header("Content-Type", "application/json; charset=utf-8")
        handler.send_header("Content-Length", str(len(body)))
        handler.end_headers()
        handler.wfile.write(body)

    class AarisAPI(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args) -> None:
            return

        def _is_authorized(self) -> bool:
            if not api_token:
                return True
            auth = (self.headers.get("Authorization") or "").strip()
            if auth.startswith("Bearer ") and auth.removeprefix("Bearer ").strip() == api_token:
                return True
            api_key = (self.headers.get("X-API-Key") or "").strip()
            return api_key == api_token

        def do_GET(self) -> None:
            if self.path == "/health":
                _json(self, 200, {"status": "ok"})
                return
            _json(self, 404, {"error": "not_found"})

        def do_POST(self) -> None:
            if self.path != "/api/chat":
                _json(self, 404, {"error": "not_found"})
                return

            if not self._is_authorized():
                _json(self, 401, {"error": "unauthorized"})
                return

            client = self.client_address[0] if self.client_address else "unknown"
            if not limiter.allow(str(client)):
                _json(
                    self,
                    429,
                    {"error": "rate_limited", "detail": f"máximo {max_rpm} peticiones/min por cliente"},
                )
                return

            try:
                length = int(self.headers.get("Content-Length") or "0")
            except ValueError:
                _json(self, 400, {"error": "bad_request", "detail": "invalid_content_length"})
                return

            if length <= 0:
                _json(self, 400, {"error": "bad_request", "detail": "empty_body"})
                return

            if length > max_body_bytes:
                _json(self, 413, {"error": "payload_too_large", "max_bytes": max_body_bytes})
                return

            try:
                raw = self.rfile.read(length)
            except OSError:
                _json(self, 400, {"error": "bad_request", "detail": "read_failed"})
                return

            try:
                data = json.loads(raw.decode("utf-8", errors="replace"))
            except json.JSONDecodeError:
                _json(self, 400, {"error": "bad_request", "detail": "invalid_json"})
                return

            prompt = (data.get("prompt") or "").strip() if isinstance(data, dict) else ""
            if not prompt:
                _json(self, 400, {"error": "bad_request", "detail": "missing_prompt"})
                return

            try:
                reply = reply_fn(prompt)
            except Exception as e:
                _json(self, 500, {"error": "server_error", "detail": str(e)})
                return

            _json(self, 200, {"response": reply})

    server_address = (host, port)
    httpd = HTTPServer(server_address, AarisAPI)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
