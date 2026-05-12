from __future__ import annotations

import json
import os
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Callable, Optional


def start_server(
    reply_fn: Callable[[str], str],
    *,
    host: str = "127.0.0.1",
    port: int = 8080,
    api_token: Optional[str] = None,
    max_body_bytes: int = 1024 * 1024,
) -> None:
    api_token = (api_token or "").strip()

    def _json(status: int, payload: dict) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        handler.send_response(status)
        handler.send_header("Content-Type", "application/json; charset=utf-8")
        handler.send_header("Content-Length", str(len(body)))
        handler.end_headers()
        handler.wfile.write(body)

    class JarvisAPI(BaseHTTPRequestHandler):
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
            nonlocal handler
            handler = self
            if self.path == "/health":
                _json(200, {"status": "ok"})
                return
            _json(404, {"error": "not_found"})

        def do_POST(self) -> None:
            nonlocal handler
            handler = self

            if self.path != "/api/chat":
                _json(404, {"error": "not_found"})
                return

            if not self._is_authorized():
                _json(401, {"error": "unauthorized"})
                return

            try:
                length = int(self.headers.get("Content-Length") or "0")
            except Exception:
                _json(400, {"error": "bad_request", "detail": "invalid_content_length"})
                return

            if length <= 0:
                _json(400, {"error": "bad_request", "detail": "empty_body"})
                return

            if length > max_body_bytes:
                _json(413, {"error": "payload_too_large", "max_bytes": max_body_bytes})
                return

            try:
                raw = self.rfile.read(length)
            except Exception:
                _json(400, {"error": "bad_request", "detail": "read_failed"})
                return

            try:
                data = json.loads(raw.decode("utf-8", errors="replace"))
            except Exception:
                _json(400, {"error": "bad_request", "detail": "invalid_json"})
                return

            prompt = (data.get("prompt") or "").strip() if isinstance(data, dict) else ""
            if not prompt:
                _json(400, {"error": "bad_request", "detail": "missing_prompt"})
                return

            try:
                reply = reply_fn(prompt)
            except Exception as e:
                _json(500, {"error": "server_error", "detail": str(e)})
                return

            _json(200, {"response": reply})

    handler: BaseHTTPRequestHandler

    env_host = os.environ.get("JARVIS_HTTP_HOST", "").strip()
    env_port = os.environ.get("JARVIS_HTTP_PORT", "").strip()
    if env_host:
        host = env_host
    if env_port:
        try:
            port = int(env_port)
        except Exception:
            pass

    server_address = (host, port)
    httpd = HTTPServer(server_address, JarvisAPI)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
