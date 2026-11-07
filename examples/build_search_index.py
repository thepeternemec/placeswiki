#!/usr/bin/env python3
"""Build the site's typeahead index from a placeswiki database.

    python3 examples/build_search_index.py data/berlin.sqlite site/places.json

Keeps it tiny: name, id and coordinates only, rounded to five decimals.
"""

import json
import sqlite3
import sys


def main(db_path, out_path):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT id, name, lat, lng, wikidata_id FROM places"
        " WHERE name IS NOT NULL AND name != '' ORDER BY name"
    ).fetchall()
    records = [
        {
            "n": row["name"],
            "i": row["wikidata_id"] or row["id"],
            "lat": round(row["lat"], 5),
            "lon": round(row["lng"], 5),
        }
        for row in rows
    ]
    with open(out_path, "w", encoding="utf-8") as handle:
        json.dump(records, handle, ensure_ascii=False, separators=(",", ":"))
    print("%d places -> %s" % (len(records), out_path))


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
