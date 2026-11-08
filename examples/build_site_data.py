#!/usr/bin/env python3
"""Build the site's city and place indexes from placeswiki databases.

    python3 examples/build_site_data.py site/data \
        --city berlin:Berlin:Germany:/tmp/berlin.sqlite \
        --city vienna:Vienna:Austria:/tmp/vienna.sqlite

Writes ``cities.json`` (for the first search step) and one compact file per
city (for the second step). Arrays, not objects: 10 000 places cost ~600 KB.
"""

import json
import os
import sqlite3
import sys


def read_city(db_path):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT name, wikidata_id, id, lat, lng FROM places"
        " WHERE name IS NOT NULL AND name != '' ORDER BY name"
    ).fetchall()
    places = [
        [row["name"], row["wikidata_id"] or row["id"], round(row["lat"], 5), round(row["lng"], 5)]
        for row in rows
    ]
    conn.close()
    return places


def main(out_dir, specs):
    os.makedirs(out_dir, exist_ok=True)
    cities = []
    for spec in specs:
        slug, name, country, db_path = spec.split(":", 3)
        places = read_city(db_path)
        if not places:
            raise SystemExit("no places in %s" % db_path)
        path = os.path.join(out_dir, slug + ".json")
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(places, handle, ensure_ascii=False, separators=(",", ":"))
        cities.append({
            "s": slug,
            "n": name,
            "c": country,
            "count": len(places),
            "lat": round(sum(p[2] for p in places) / len(places), 4),
            "lon": round(sum(p[3] for p in places) / len(places), 4),
        })
        print("%-8s %6d places -> %s (%.0f KB)" % (name, len(places), path, os.path.getsize(path) / 1024))

    with open(os.path.join(out_dir, "cities.json"), "w", encoding="utf-8") as handle:
        json.dump(cities, handle, ensure_ascii=False, separators=(",", ":"))
    print("cities.json: %d cities" % len(cities))


if __name__ == "__main__":
    out = sys.argv[1]
    specs = [sys.argv[i + 1] for i, arg in enumerate(sys.argv) if arg == "--city"]
    main(out, specs)
