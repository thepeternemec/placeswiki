"""Outbound webhooks: tell your stack when the dataset changed.

A static SQLite file is easy to serve but hard to keep in sync with the rest of
a product: a search index, a CDN cache, a mobile app's bundled database. This
module sends a signed JSON event after a build or publish, so downstream systems
can refresh instead of polling.

The signature is HMAC-SHA256 over the exact request body, in the
``X-Placeswiki-Signature: sha256=<hex>`` header, the same convention Stripe and
GitHub use. Receivers must verify it before trusting the payload.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
import urllib.error
import urllib.request

EVENT = "dataset.updated"
SIGNATURE_HEADER = "X-Placeswiki-Signature"
EVENT_HEADER = "X-Placeswiki-Event"
USER_AGENT = "placeswiki-webhook/1.0"


def dataset_summary(conn):
    """Counts a receiver can use to decide whether to reindex."""
    return {
        "places": conn.execute("SELECT COUNT(*) FROM places").fetchone()[0],
        "photos": conn.execute("SELECT COUNT(*) FROM place_photos").fetchone()[0],
        "google_linked": conn.execute(
            "SELECT COUNT(*) FROM places WHERE google_place_id IS NOT NULL"
        ).fetchone()[0],
    }


def build_event(conn, event=EVENT, version="unknown"):
    return {
        "event": event,
        "dataset": dataset_summary(conn),
        "source": "placeswiki/%s" % version,
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }


def sign(body, secret):
    """Hex HMAC-SHA256 of the raw body."""
    return hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()


def send(url, payload, secret="", timeout=10, attempts=3, sleeper=time.sleep):
    """POST a signed event; retries 5xx and connection errors.

    Returns ``{"delivered": bool, "status": int|None, "attempts": int}``.
    """
    body = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    headers = {
        "Content-Type": "application/json",
        "User-Agent": USER_AGENT,
        EVENT_HEADER: payload.get("event", EVENT),
    }
    if secret:
        headers[SIGNATURE_HEADER] = "sha256=" + sign(body, secret)

    status = None
    for attempt in range(1, attempts + 1):
        request = urllib.request.Request(url, data=body, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                status = response.status
            return {"delivered": 200 <= status < 300, "status": status, "attempts": attempt}
        except urllib.error.HTTPError as exc:
            status = exc.code
            if exc.code < 500:
                return {"delivered": False, "status": status, "attempts": attempt}
        except (urllib.error.URLError, TimeoutError):
            status = None
        if attempt < attempts:
            sleeper(2 ** (attempt - 1))
    return {"delivered": False, "status": status, "attempts": attempts}


def verify(body, secret, signature):
    """Receiver-side check; constant-time comparison."""
    expected = "sha256=" + sign(body, secret)
    return hmac.compare_digest(expected, signature or "")
