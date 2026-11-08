"""Bulk pipeline: stage a worldwide place list, then enrich it into ``places``.

Two phases, deliberately separated:

``stage``
    SPARQL only. Writes one row per Wikidata item to ``wd_places``. No
    per-place API calls, so 2.2 M rows cost ~2.2 M/500 requests (4 420), not
    2.2 M. Resumable per country.

``enrich``
    Resolves each staged row's Commons image (``P18``) in batches of 50 and
    writes clean ``places`` rows with id ``wc:Q…``. Skips anything already
    enriched, so it can be stopped and restarted at any point.

The point of the split is that the expensive, failure-prone network work
happens once per place down a path that can be interrupted.
"""

from __future__ import annotations

import json
import time

from .images import fetch_imageinfo
from .intel import clean_author
from .schema import fold_text, infer_types, slugify
from .wikidata import heritage_query, landmark_query, parse_row

WD_DDL = """
CREATE TABLE IF NOT EXISTS wd_places (
    qid              TEXT PRIMARY KEY,
    label            TEXT,
    lat              REAL,
    lon              REAL,
    enwiki_title     TEXT,
    image_file       TEXT,
    commons_category TEXT,
    heritage         TEXT,
    country          TEXT,
    status           TEXT NOT NULL DEFAULT 'pending',
    place_id         TEXT,
    error            TEXT,
    fetched_at       REAL
);
CREATE INDEX IF NOT EXISTS idx_wd_status ON wd_places (status);
CREATE INDEX IF NOT EXISTS idx_wd_country ON wd_places (country);
"""

BATCH = 500


def ensure_wd_schema(conn):
    conn.executescript(WD_DDL)


def stage(
    conn,
    client,
    country=None,
    page_size=BATCH,
    limit=None,
    log=None,
    bbox=None,
    located_in=None,
    scope="heritage",
):
    """Fetch one page (or all pages) of the heritage list into ``wd_places``.

    Rows are merged by QID: an item with three heritage designations arrives as
    three SPARQL solutions, and we want one staging row. ``ORDER BY ?item``
    keeps those solutions adjacent, so merging inside a page covers almost
    everything; the remainder is merged on conflict.

    Returns ``{"rows", "requests", "done"}``.
    """
    ensure_wd_schema(conn)
    rows_total = 0
    requests = 0
    offset = 0
    stamp = time.time()

    while True:
        size = page_size if limit is None else min(page_size, limit - rows_total)
        if size <= 0:
            break
        query = landmark_query if scope == "landmarks" else heritage_query
        payload = client.query(
            query(limit=size, offset=offset, country=country, bbox=bbox, located_in=located_in)
        )
        requests += 1
        if not payload:
            break

        merged = {}
        for raw in payload:
            record = parse_row(raw)
            if not record["qid"] or record["lat"] is None or record["lon"] is None:
                continue
            current = merged.setdefault(record["qid"], dict(record, heritage=[]))
            if record["heritage"]:
                current["heritage"].append(record["heritage"])
            for field in ("label", "image_file", "commons_category", "enwiki_title", "country"):
                if not current.get(field) and record.get(field):
                    current[field] = record[field]

        for record in merged.values():
            existing = conn.execute(
                "SELECT heritage FROM wd_places WHERE qid = ?", (record["qid"],)
            ).fetchone()
            heritage = set(json.loads(existing[0])) if existing and existing[0] else set()
            heritage.update(record["heritage"])
            conn.execute(
                """
                INSERT INTO wd_places (qid, label, lat, lon, enwiki_title, image_file,
                                       commons_category, heritage, country, status,
                                       fetched_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?)
                ON CONFLICT(qid) DO UPDATE SET
                    label=excluded.label, lat=excluded.lat, lon=excluded.lon,
                    enwiki_title=COALESCE(excluded.enwiki_title, wd_places.enwiki_title),
                    image_file=COALESCE(excluded.image_file, wd_places.image_file),
                    commons_category=COALESCE(excluded.commons_category, wd_places.commons_category),
                    heritage=excluded.heritage, country=excluded.country
                """,
                (
                    record["qid"],
                    record["label"],
                    record["lat"],
                    record["lon"],
                    record["enwiki_title"],
                    record["image_file"],
                    record["commons_category"],
                    json.dumps(sorted(heritage)),
                    record["country"],
                    stamp,
                ),
            )
            rows_total += 1
        conn.commit()
        offset += len(payload)
        if log:
            log("staged %d items (offset %d)" % (rows_total, offset))
        if len(payload) < size:
            break
    return {"rows": rows_total, "requests": requests, "done": True}


def stage_countries(conn, client, page_size=BATCH, limit=None, log=None, scope="heritage"):
    """Stage every country, largest first. Resumable: countries already staged
    are skipped by qid de-duplication, not by bookkeeping."""
    from .wikidata import countries_query

    total = {"rows": 0, "requests": 0, "countries": 0}
    for row in client.query(countries_query()):
        country = (row.get("country") or "").rsplit("/", 1)[-1]
        if not country:
            continue
        result = stage(
            conn, client, country=country, page_size=page_size, limit=limit, log=log, scope=scope
        )
        total["rows"] += result["rows"]
        total["requests"] += result["requests"]
        total["countries"] += 1
        if log:
            log("country %s: +%d rows" % (country, result["rows"]))
        if limit and total["rows"] >= limit:
            break
    return total


LANGUAGE_FALLBACKS = "en|mul|sl|de|it|fr|es|hr"


def _label_from(entity):
    """Pick the best label from an entity: English, then anything."""
    values = entity.get("labels") or {}
    if not values:
        return ""
    if "en" in values:
        return values["en"]["value"]
    return next(iter(values.values()))["value"]


def fetch_labels(api, qids, batch=50):
    """Resolve display labels for items whose SPARQL label was missing.

    Two passes: first the language list we prefer, then all languages for
    whatever is still blank. Without the second pass, an item labelled only in
    an unexpected language is dropped for no good reason.
    """
    labels = {}
    qids = [qid for qid in qids if qid]

    for start in range(0, len(qids), batch):
        chunk = qids[start : start + batch]
        payload = api.get(
            action="wbgetentities",
            ids="|".join(chunk),
            props="labels",
            languages=LANGUAGE_FALLBACKS,
            formatversion=2,
        )
        for qid, entity in (payload.get("entities") or {}).items():
            label = _label_from(entity)
            if label:
                labels[qid] = label

    missing = [qid for qid in qids if qid not in labels]
    for start in range(0, len(missing), batch):
        chunk = missing[start : start + batch]
        payload = api.get(
            action="wbgetentities",
            ids="|".join(chunk),
            props="labels",
            formatversion=2,
        )
        for qid, entity in (payload.get("entities") or {}).items():
            label = _label_from(entity)
            if label:
                labels[qid] = label

    return labels


def retry_failed(conn):
    """Move rows marked failed back to pending, for a second attempt."""
    ensure_wd_schema(conn)
    cursor = conn.execute("UPDATE wd_places SET status='pending', error=NULL WHERE status='failed'")
    conn.commit()
    return cursor.rowcount


def pending(conn, limit=None):
    sql = "SELECT * FROM wd_places WHERE status = 'pending' ORDER BY qid"
    if limit:
        sql += " LIMIT %d" % int(limit)
    return conn.execute(sql).fetchall()


def enrich(conn, commons, limit=None, log=None, wikidata=None):
    """Turn staged rows into clean ``places`` (+ photos) and mark them done.

    Only ``P18`` images are resolved, because they are already in the SPARQL
    result — using Commons categories would cost one request per place instead
    of one per fifty.
    """
    rows = pending(conn, limit)
    if not rows:
        return {"places": 0, "photos": 0, "requests": 0}

    unlabeled = [row["qid"] for row in rows if not (row["label"] or row["enwiki_title"])]
    if unlabeled and not wikidata and log:
        log("%d rows have no label and no Wikidata client was supplied" % len(unlabeled))
    resolved_labels = fetch_labels(wikidata, unlabeled) if (unlabeled and wikidata) else {}

    files = [row["image_file"] for row in rows if row["image_file"]]
    images = {}
    if files:
        for record in fetch_imageinfo(commons, files):
            images[record["file"]] = record

    stamp = time.time()
    created = photos = 0
    for row in rows:
        name = row["label"] or row["enwiki_title"] or resolved_labels.get(row["qid"], "")
        if not name:
            conn.execute(
                "UPDATE wd_places SET status='failed', error='no label' WHERE qid = ?",
                (row["qid"],),
            )
            continue

        place_id = "wc:" + row["qid"]
        types = infer_types(
            {
                "title": name,
                "categories": [row["commons_category"]] if row["commons_category"] else [],
                "infobox": {},
            }
        )
        heritage = json.loads(row["heritage"] or "[]")
        conn.execute(
            """
            INSERT INTO places (id, name, name_folded, language_code, lat, lng, types, primary_type,
                                wikidata_id, wikipedia_url, commons_category,
                                heritage_designations, source, created_at, updated_at)
            VALUES (?, ?, ?, 'en', ?, ?, ?, ?, ?, ?, ?, ?, 'wikidata', ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                name=excluded.name, name_folded=excluded.name_folded,
                lat=excluded.lat, lng=excluded.lng,
                types=excluded.types, primary_type=excluded.primary_type,
                commons_category=excluded.commons_category,
                heritage_designations=excluded.heritage_designations,
                updated_at=excluded.updated_at
            """,
            (
                place_id,
                name,
                fold_text(name),
                row["lat"],
                row["lon"],
                json.dumps(types),
                types[0] if types else None,
                row["qid"],
                ("https://en.wikipedia.org/wiki/" + row["enwiki_title"].replace(" ", "_"))
                if row["enwiki_title"]
                else None,
                row["commons_category"] or None,
                json.dumps(heritage),
                stamp,
                stamp,
            ),
        )
        created += 1

        image = images.get(row["image_file"])
        if image:
            author, author_uri = clean_author(image.get("artist"))
            photo_id = "commons:" + row["image_file"][5:]
            conn.execute(
                """
                INSERT INTO place_photos (id, place_id, name, url, description_url,
                                          width_px, height_px, author_name, author_uri,
                                          license, position, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?)
                ON CONFLICT(place_id, id) DO UPDATE SET
                    url=excluded.url, license=excluded.license,
                    author_name=excluded.author_name
                """,
                (
                    photo_id,
                    place_id,
                    "places/%s/photos/%s" % (place_id, slugify(photo_id)),
                    image["url"],
                    image.get("description_url"),
                    image.get("width"),
                    image.get("height"),
                    author,
                    author_uri or None,
                    image.get("license"),
                    stamp,
                ),
            )
            photos += 1

        conn.execute(
            "UPDATE wd_places SET status='enriched', place_id=?, error=NULL WHERE qid=?",
            (place_id, row["qid"]),
        )

    conn.commit()
    if log:
        log("enriched %d places, %d photos" % (created, photos))
    return {"places": created, "photos": photos, "requests": 0}


def status(conn):
    """Counts per staging status, plus what has made it into ``places``."""
    ensure_wd_schema(conn)
    counts = {}
    for row in conn.execute("SELECT status, COUNT(*) FROM wd_places GROUP BY status"):
        counts[row[0]] = row[1]
    return {
        "staged": sum(counts.values()),
        "pending": counts.get("pending", 0),
        "enriched": counts.get("enriched", 0),
        "failed": counts.get("failed", 0),
        "places": conn.execute("SELECT COUNT(*) FROM places").fetchone()[0],
        "photos": conn.execute("SELECT COUNT(*) FROM place_photos").fetchone()[0],
    }
