#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Shared test fixtures and local HTTP echo server for event dispatcher testing.
"""

import json
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler


class WebhookTestServerHandler(BaseHTTPRequestHandler):
    """Local HTTP request handler recording POST requests for test assertion."""

    def log_message(self, format, *args):
        # Silence console log noise during automated test run
        pass

    def do_POST(self):
        content_length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_length)

        # Allow tests to configure simulated error responses
        if getattr(self.server, "fail_next_n", 0) > 0:
            self.server.fail_next_n -= 1
            self.send_response(500)
            self.end_headers()
            self.wfile.write(b'{"error": "Internal Server Error"}')
            return

        self.server.received_requests.append({
            "path": self.path,
            "headers": {k.lower(): v for k, v in self.headers.items()},
            "body": json.loads(body.decode("utf-8")),
            "raw_body": body,
        })

        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b'{"status": "success"}')


class WebhookTestServer:
    """Local HTTP Server running on an OS-assigned ephemeral port."""

    def __init__(self):
        self.httpd = HTTPServer(("127.0.0.1", 0), WebhookTestServerHandler)
        self.httpd.received_requests = []
        self.httpd.fail_next_n = 0
        self.port = self.httpd.server_port
        self.url = "http://127.0.0.1:{}/webhook".format(self.port)
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)

    def start(self):
        self.thread.start()

    def stop(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.thread.join(timeout=2.0)

