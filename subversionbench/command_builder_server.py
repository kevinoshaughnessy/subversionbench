"""
The local web server behind the run-command builder.

It answers three requests and does nothing else: the page, the form's options,
and the command assembled from a filled-in form. It runs no command, reads no
environment variable and no file but the scenario sidecars, so the one thing it
can hand a person is a line of text to run themselves.

Bound to the loopback address only. A request whose Host header is not that
address is refused, which closes the rebinding route by which a page on another
site could otherwise reach a server that is only listening locally, and a POST
must be JSON, which a cross-site form cannot send.
"""

import json
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .command_builder import build, options
from .command_builder_page import PAGE

HOST = "127.0.0.1"
MAX_BODY = 64 * 1024


def make_handler(known_models):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def _send(self, status, body: bytes, kind: str):
            self.send_response(status)
            self.send_header("Content-Type", kind)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _json(self, status, document):
            self._send(status, json.dumps(document).encode(), "application/json")

        def _host_ok(self) -> bool:
            host = (self.headers.get("Host") or "").rpartition(":")[0]
            return host in (HOST, "localhost")

        def do_GET(self):
            if not self._host_ok():
                return self._json(403, {"error": "bad host"})
            if self.path == "/":
                return self._send(200, PAGE.encode(), "text/html; charset=utf-8")
            if self.path == "/api/options":
                return self._json(200, options(known_models))
            return self._json(404, {"error": "not found"})

        def do_POST(self):
            if not self._host_ok():
                return self._json(403, {"error": "bad host"})
            if self.path != "/api/command":
                return self._json(404, {"error": "not found"})
            if self.headers.get("Content-Type", "").split(";")[0] != "application/json":
                return self._json(415, {"error": "json only"})
            length = int(self.headers.get("Content-Length") or 0)
            if length > MAX_BODY:
                return self._json(413, {"error": "too large"})
            try:
                spec = json.loads(self.rfile.read(length))
            except ValueError:
                return self._json(400, {"error": "bad json"})
            if not isinstance(spec, dict):
                return self._json(400, {"error": "bad form"})
            return self._json(200, build(spec))

    return Handler


def serve(known_models=(), port=8765, open_browser=True) -> None:
    server = ThreadingHTTPServer((HOST, port), make_handler(known_models))
    url = f"http://{HOST}:{server.server_address[1]}/"
    print(f"Run builder at {url}  (Ctrl-C to stop). It builds commands and runs none.")
    if open_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
