"""Tests for the outbound webhook."""

from __future__ import annotations

import hashlib
import hmac
import json
import sqlite3
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from placeswiki.notify import build_event, send, sign, verify
from placeswiki.schema import ensure_schema


class Receiver(BaseHTTPRequestHandler):
    attempts = 0
    fail_first = 0
    captured = []

    def log_message(self, *args):
        pass

    def do_POST(self):
        body = self.rfile.read(int(self.headers["Content-Length"]))
        Receiver.attempts += 1
        Receiver.captured.append((dict(self.headers), body))
        if Receiver.attempts <= Receiver.fail_first:
            self.send_response(503)
            self.end_headers()
            return
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"ok")


class TestSigning(unittest.TestCase):
    def test_signature_is_hmac_sha256(self):
        body = b'{"a":1}'
        expected = hmac.new(b"s", body, hashlib.sha256).hexdigest()
        self.assertEqual(sign(body, "s"), expected)

    def test_verify_accepts_and_rejects(self):
        body = b'{"a":1}'
        self.assertTrue(verify(body, "s", "sha256=" + sign(body, "s")))
        self.assertFalse(verify(body, "s", "sha256=deadbeef"))
        self.assertFalse(verify(body, "s", ""))


class TestSend(unittest.TestCase):
    def setUp(self):
        Receiver.attempts = 0
        Receiver.fail_first = 0
        Receiver.captured = []
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Receiver)
        self.url = "http://127.0.0.1:%d/hook" % self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()

    def test_delivers_signed_event(self):
        result = send(
            self.url, {"event": "dataset.updated", "dataset": {"places": 1}}, secret="s3cret"
        )
        self.assertTrue(result["delivered"])
        headers, body = Receiver.captured[0]
        self.assertTrue(verify(body, "s3cret", headers.get("X-Placeswiki-Signature")))
        self.assertEqual(headers.get("X-Placeswiki-Event"), "dataset.updated")
        self.assertEqual(json.loads(body)["dataset"]["places"], 1)

    def test_retries_on_server_error(self):
        Receiver.fail_first = 1
        result = send(self.url, {"event": "dataset.updated"}, sleeper=lambda s: None)
        self.assertTrue(result["delivered"])
        self.assertEqual(result["attempts"], 2)

    def test_client_error_is_not_retried(self):
        class Reject(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_POST(self):
                self.send_response(400)
                self.end_headers()

        server = ThreadingHTTPServer(("127.0.0.1", 0), Reject)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            result = send(
                "http://127.0.0.1:%d/x" % server.server_address[1],
                {},
                attempts=3,
                sleeper=lambda s: None,
            )
            self.assertFalse(result["delivered"])
            self.assertEqual(result["attempts"], 1)
        finally:
            server.shutdown()
            server.server_close()


class TestEvent(unittest.TestCase):
    def test_dataset_summary(self):
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        ensure_schema(conn)
        conn.execute("INSERT INTO places (id, name, lat, lng, types) VALUES ('p', 'P', 1, 1, '[]')")
        conn.commit()
        event = build_event(conn, version="9.9.9")
        self.assertEqual(event["dataset"]["places"], 1)
        self.assertEqual(event["source"], "placeswiki/9.9.9")
        self.assertIn("generated_at", event)
        conn.close()


if __name__ == "__main__":
    unittest.main()
