"""Place identity: Wikimedia entity -> stable id, and entity lookup by position.

Every place needs an id that is not Google's. The natural one is the Wikidata
item, because it survives renames, merges and language moves. This module
resolves the Wikipedia article a crawl already knows to its QID, then pulls the
claims that make the place useful: coordinates, heritage designation, Commons
category and lead image.
"""

from __future__ import annotations

import json
import math

from .intel import ensure_intel_schema, rank_photos
from .schema import photo_resource_name


def _values(entity, prop):
    out = []
    for claim in entity.get("claims", {}).get(prop, []):
        value = claim.get("mainsnak", {}).get("datavalue", {}).get("value")
        if value is not None:
            out.append(value)
    return out


def _coord(entity):
    values = _values(entity, "P625")
    if not values:
        return None, None
    return values[0].get("latitude"), values[0].get("longitude")


def _distance_km(lat1, lon1, lat2, lon2):
    lon1, lat1, lon2, lat2 = map(math.radians, (lon1, lat1, lon2, lat2))
    h = (
        math.sin((lat2 - lat1) / 2) ** 2
        + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    )
    return 2 * 6371.0 * math.asin(math.sqrt(h))


def _title_from_url(url):
    if not url:
        return ""
    return url.split("/wiki/", 1)[-1].replace("_", " ")


def _entity_record(qid, entity):
    lat, lon = _coord(entity)
    return {
        "qid": qid,
        "lat": lat,
        "lon": lon,
        "heritage": [value.get("id", "") for value in _values(entity, "P1435")],
        "commons_category": (_values(entity, "P373") or [""])[0],
        "image": (_values(entity, "P18") or [""])[0],
    }


def resolve_titles(api, titles):
    """Map enwiki titles to Wikidata records, 50 per request."""
    records = {}
    titles = [title for title in titles if title]
    for start in range(0, len(titles), 50):
        chunk = titles[start : start + 50]
        payload = api.get(
            action="wbgetentities",
            sites="enwiki",
            titles="|".join(chunk),
            props="claims|sitelinks",
            formatversion=2,
        )
        for qid, entity in (payload.get("entities") or {}).items():
            if not qid.startswith("Q"):
                continue
            record = _entity_record(qid, entity)
            record["title"] = entity.get("sitelinks", {}).get("enwiki", {}).get("title", "")
            records[record["title"] or qid] = record
    return records


def enrich_from_wikidata(conn, api, limit=100, log=None):
    """Fill ``wikidata_id`` and claims for crawled places that lack them."""
    ensure_intel_schema(conn)
    rows = conn.execute(
        """
        SELECT id, name, wikipedia_url FROM places
        WHERE (wikidata_id IS NULL OR wikidata_id = '')
          AND wikipedia_url IS NOT NULL AND wikipedia_url != ''
        ORDER BY name LIMIT ?
        """,
        (limit,),
    ).fetchall()
    if not rows:
        return {"places": 0, "resolved": 0, "photos": 0}

    by_title = {}
    for row in rows:
        by_title.setdefault(_title_from_url(row["wikipedia_url"]), []).append(row)

    records = resolve_titles(api, list(by_title))
    resolved = photos = 0
    for title, place_rows in by_title.items():
        record = None
        for candidate_title, candidate in records.items():
            if candidate_title.lower() == title.lower():
                record = candidate
                break
        if not record:
            continue
        for row in place_rows:
            conn.execute(
                # Wikidata's P373 is canonical; keep the crawled category only
                # when Wikidata has none.
                "UPDATE places SET wikidata_id = ?, heritage_designations = ?,"
                " commons_category = COALESCE(NULLIF(?, ''), commons_category)"
                " WHERE id = ?",
                (
                    record["qid"],
                    json.dumps(record["heritage"]),
                    record["commons_category"] or None,
                    row["id"],
                ),
            )
            resolved += 1
            if record["image"]:
                photo_id = "commons:" + record["image"].replace("_", " ")
                existing = conn.execute(
                    "SELECT 1 FROM place_photos WHERE place_id = ? AND id = ?",
                    (row["id"], photo_id),
                ).fetchone()
                if not existing:
                    conn.execute(
                        "INSERT INTO place_photos (place_id, id, name, url, license, source)"
                        " VALUES (?, ?, ?, ?, NULL, 'p18')",
                        (
                            row["id"],
                            photo_id,
                            photo_resource_name(row["id"], photo_id),
                            "https://commons.wikimedia.org/wiki/File:" + record["image"],
                        ),
                    )
                    photos += 1
    conn.commit()
    if photos:
        rank_photos(conn)
    if log:
        log("resolved %d places, added %d lead images" % (resolved, photos))
    return {"places": len(rows), "resolved": resolved, "photos": photos}


def lookup(api, name, lat, lon, max_km=2.0, limit=5):
    """Search Wikidata by name, keep candidates near the given position."""
    search = api.get(
        action="wbsearchentities",
        search=name,
        language="en",
        limit=limit,
        format="json",
        formatversion=2,
    )
    ids = [hit["id"] for hit in search.get("search", []) if hit.get("id", "").startswith("Q")]
    if not ids:
        return []
    payload = api.get(
        action="wbgetentities",
        ids="|".join(ids),
        props="claims|labels|descriptions",
        languages="en",
        formatversion=2,
    )
    out = []
    for qid in ids:
        entity = (payload.get("entities") or {}).get(qid)
        if not entity:
            continue
        record = _entity_record(qid, entity)
        if record["lat"] is None:
            continue
        distance = _distance_km(lat, lon, record["lat"], record["lon"])
        if distance > max_km:
            continue
        record["distance_km"] = round(distance, 3)
        record["label"] = (entity.get("labels", {}).get("en") or {}).get("value", "")
        record["description"] = (entity.get("descriptions", {}).get("en") or {}).get("value", "")
        out.append(record)
    return sorted(out, key=lambda item: item["distance_km"])
