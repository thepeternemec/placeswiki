#!/usr/bin/env python3
"""A webhook receiver that verifies the signature before trusting the payload.

    PLACESWIKI_WEBHOOK_SECRET=s3cret python3 examples/webhook_receiver.py 8160

Every other webhook example on the internet parses first and verifies never.
This one rejects unsigned or tampered requests with a 401.
"""

import hashlib
import hmac
import json
import os
from http.server import BaseHTTPRequestHandler, HTTPServer

SECRET = os.environ.get("PLACESWIKI_WEBHOOK_SECRET", "")


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_POST(self):
        body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
        signature = self.headers.get("X-Placeswiki-Signature", "")
        expected = "sha256=" + hmac.new(SECRET.encode(), body, hashlib.sha256).hexdigest()
        if not SECRET or not hmac.compare_digest(expected, signature):
            self.send_response(401)
            self.end_headers()
            self.wfile.write(b"bad signature")
            return

        payload = json.loads(body)
        print("event:", self.headers.get("X-Placeswiki-Event"))
        print("dataset:", payload.get("dataset"))
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"ok")


if __name__ == "__main__":
    import sys

    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8160
    print("listening on http://127.0.0.1:%d/hook" % port)
    HTTPServer(("127.0.0.1", port), Handler).serve_forever()
