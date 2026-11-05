#!/usr/bin/env python3
"""Build a tiny offline database for demos, tests and CI.

    python3 examples/fixture_db.py /tmp/demo.sqlite

No network. Three places, three photos, one Google link.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import sqlite3  # noqa: E402

from placeswiki.intel import rank_photos  # noqa: E402
from placeswiki.schema import ensure_schema  # noqa: E402

PLACES = [
    ("wc:Q10285", "Colosseum", 41.8902, 12.4922, '["historical_landmark"]', "Colosseum"),
    (
        "wc:Q5786",
        "Arch of Constantine",
        41.8897,
        12.4908,
        '["historical_landmark"]',
        "Arch of Constantine",
    ),
    ("wc:Q1570519", "Colossus of Nero", 41.8911, 12.4914, '["tourist_attraction"]', ""),
]

PHOTOS = [
    ("commons:Colosseo 2020.jpg", "wc:Q10285", 12051, 8442, "CC BY-SA 4.0", "Example Author"),
    ("commons:Arch.jpg", "wc:Q5786", 4000, 3000, "CC0", "Another Author"),
]


def main(path="/tmp/fixture.sqlite"):
    if os.path.exists(path):
        os.unlink(path)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    ensure_schema(conn)
    for place_id, name, lat, lng, types, category in PLACES:
        conn.execute(
            "INSERT INTO places (id, name, lat, lng, types, primary_type, commons_category)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)",
            (place_id, name, lat, lng, types, types.strip('[]"'), category or None),
        )
    for photo_id, place_id, width, height, license_name, author in PHOTOS:
        conn.execute(
            "INSERT INTO place_photos (place_id, id, name, url, width_px, height_px,"
            " license, author_name, source) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'p18')",
            (
                place_id,
                photo_id,
                "places/%s/photos/x" % place_id,
                "https://upload.wikimedia.org/%s.jpg" % photo_id.split(":")[-1].replace(" ", "_"),
                width,
                height,
                license_name,
                author,
            ),
        )
    conn.execute(
        "INSERT INTO place_links (place_id, google_place_id, is_primary, method, confidence)"
        " VALUES ('wc:Q10285', 'ChIJrTLr-GyuEmsRBfy61i59si0', 1, 'import', 0.9)"
    )
    conn.execute(
        "UPDATE places SET google_place_id='ChIJrTLr-GyuEmsRBfy61i59si0' WHERE id='wc:Q10285'"
    )
    conn.commit()
    rank_photos(conn)
    conn.commit()
    conn.close()
    print(path)
    return path


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "/tmp/fixture.sqlite")
