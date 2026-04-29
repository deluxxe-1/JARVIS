"""
JARVIS HTTP Server — minimal REST API for external integrations.

Provides a POST /api/chat endpoint that accepts a JSON body with a 'prompt'
field and returns a JSON response with the assistant's reply.
"""

from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any

from rich.console import Console

console = Console()


def start_server(
    system_prompt: str,
    available_tools: list,
    tool_groups: dict[str, list],
    tool_map: dict[str, Any],
    opts: dict[str, Any],
    model: str,
    port: int = 8080,
) -> None:
    """Start the JARVIS HTTP daemon on the given port."""
    from jarvis.tool_selector import _select_tools

    # Import lazily to avoid circular deps
    from _legacy_main import _run_tool_loop

    class JarvisAPI(BaseHTTPRequestHandler):
        def do_POST(self):
            if self.path == '/api/chat':
                length = int(self.headers.get('Content-Length', '0'))
                post_data = self.rfile.read(length)
                data = json.loads(post_data.decode('utf-8'))
                prompt = data.get('prompt', '')
                msgs = [{"role": "system", "content": system_prompt}] + [{"role": "user", "content": prompt}]
                active = _select_tools(prompt, available_tools, tool_groups)
                reply = _run_tool_loop(msgs, active, tool_map, opts)
                self.send_response(200)
                self.send_header('Content-Type', 'application/json; charset=utf-8')
                self.end_headers()
                self.wfile.write(json.dumps({"response": reply}, ensure_ascii=False).encode('utf-8'))
            else:
                self.send_response(404)
                self.end_headers()

    server_address = ('', port)
    httpd = HTTPServer(server_address, JarvisAPI)
    console.print(f"[bold green]Starting daemon server on port {port}...[/bold green]")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
