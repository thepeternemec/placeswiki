"""Photo intelligence: score, rank and expand a place's photographs.

Not every Commons photo is equally useful. A 4096 px CC0 shot with a named
author beats a 640 px GFDL thumbnail with attribution missing, and the lead
image (`P18`) beats both as a statement of intent by the community.

This module turns that into a number with reasons attached, so a client can
explain why it showed the photo it showed, and expand a place's photo set from
its Commons category when `P18` alone is thin.
"""

from __future__ import annotations

import json
import math
import re

TAG_RE = re.compile(r"<[^>]+>")

LICENSE_TIERS = (
    (("public domain", "pd-", "cc0", "pdm"), 25),
    (("cc by-sa", "cc-by-sa"), 14),
    (("cc by", "cc-by"), 18),
    (("gfdl",), 4),
)

COLUMNS = (
    ("score", "REAL"),
    ("score_reasons", "TEXT"),
    ("source", "TEXT"),
)


def ensure_intel_schema(conn):
    """Add the scoring columns if they are not there yet (idempotent)."""
    existing = {row[1] for row in conn.execute("PRAGMA table_info(place_photos)")}
    for name, kind in COLUMNS:
        if name not in existing:
            conn.execute("ALTER TABLE place_photos ADD COLUMN %s %s" % (name, kind))
    conn.commit()


def clean_author(value):
    """Commons artist fields are HTML; keep the text and the profile URL."""
    if not value:
        return "", ""
    match = re.search(r'href="([^"]+)"', value)
    uri = match.group(1) if match else ""
    if uri.startswith("//"):
        uri = "https:" + uri
    return TAG_RE.sub("", value).replace("&amp;", "&").strip(), uri


def license_points(license_name):
    lowered = (license_name or "").lower()
    for needles, points in LICENSE_TIERS:
        if any(needle in lowered for needle in needles):
            return points
    return 0


def score_photo(width, height, license_name, author, is_lead=False):
    """Return ``(score 0-100, reasons)``.

    Weights: resolution 40, licence 25, attribution 15, lead image 20. They sum
    to 100 so the number reads as a percentage of "how useful is this photo".
    """
    width = width or 0
    height = height or 0
    reasons = []

    pixels = max(1, width * height)
    resolution = min(40.0, 40.0 * min(1.0, math.sqrt(pixels) / 4000.0))
    reasons.append("%dx%d → %.0f/40 resolution" % (width, height, resolution))

    licence = license_points(license_name)
    reasons.append("%s → %d/25 licence" % (license_name or "unknown", licence))

    credit = 15 if (author or "").strip() else 0
    reasons.append("%s → %d/15 attribution" % ("author present" if credit else "no author", credit))

    lead = 20 if is_lead else 0
    if lead:
        reasons.append("lead image (P18) → 20/20")

    return round(resolution + licence + credit + lead, 1), reasons


def rank_photos(conn, place_id=None):
    """Recompute scores and set ``position`` to the ranking within each place."""
    ensure_intel_schema(conn)
    where = "WHERE place_id = ?" if place_id else ""
    params = (place_id,) if place_id else ()
    rows = conn.execute(
        "SELECT place_id, id, width_px, height_px, license, author_name, source"
        " FROM place_photos %s" % where,
        params,
    ).fetchall()

    by_place = {}
    for row in rows:
        by_place.setdefault(row["place_id"], []).append(row)

    ranked = 0
    for pid, photos in by_place.items():
        scored = []
        for photo in photos:
            author, _uri = clean_author(photo["author_name"])
            score, reasons = score_photo(
                photo["width_px"],
                photo["height_px"],
                photo["license"],
                author,
                is_lead=(photo["source"] or "p18") == "p18",
            )
            scored.append((score, reasons, photo))
        scored.sort(key=lambda item: -item[0])
        for index, (score, reasons, photo) in enumerate(scored):
            author, author_uri = clean_author(photo["author_name"])
            conn.execute(
                "UPDATE place_photos SET score = ?, score_reasons = ?, position = ?,"
                " author_name = ?, author_uri = COALESCE(?, author_uri)"
                " WHERE place_id = ? AND id = ?",
                (score, json.dumps(reasons), index, author, author_uri or None, pid, photo["id"]),
            )
            ranked += 1
    conn.commit()
    return {"ranked": ranked, "places": len(by_place)}


def best_photo(conn, place_id):
    row = conn.execute(
        "SELECT * FROM place_photos WHERE place_id = ? ORDER BY position, score DESC LIMIT 1",
        (place_id,),
    ).fetchone()
    return dict(row) if row else None


def repair_attribution(conn):
    """Strip HTML from author names and backfill author_uri where possible."""
    ensure_intel_schema(conn)
    fixed = 0
    for row in conn.execute(
        "SELECT place_id, id, author_name, author_uri FROM place_photos"
    ).fetchall():
        if not row["author_name"]:
            continue
        author, uri = clean_author(row["author_name"])
        if author != row["author_name"] or (uri and not row["author_uri"]):
            conn.execute(
                "UPDATE place_photos SET author_name = ?, author_uri = COALESCE(?, author_uri)"
                " WHERE place_id = ? AND id = ?",
                (author, uri or None, row["place_id"], row["id"]),
            )
            fixed += 1
    conn.commit()
    return {"repaired": fixed}


def collect_category_photos(conn, commons, limit_places=20, max_files=24, log=None):
    """Expand each place's photo set from its Commons category.

    Candidate discovery costs one request per place plus one per fifty files, so
    this is opt-in and capped. New rows are marked ``source='category'`` so the
    lead image keeps its bonus and the provenance stays visible.
    """
    from .images import fetch_imageinfo

    ensure_intel_schema(conn)
    places = conn.execute(
        """
        SELECT p.id, p.commons_category,
               (SELECT COUNT(*) FROM place_photos ph WHERE ph.place_id = p.id) AS n
        FROM places p
        WHERE p.commons_category IS NOT NULL AND p.commons_category != ''
          AND (SELECT COUNT(*) FROM place_photos ph WHERE ph.place_id = p.id) < ?
        ORDER BY p.name
        LIMIT ?
        """,
        (max_files, limit_places),
    ).fetchall()

    added = 0
    for place in places:
        files = []
        for member in commons.paginate(
            list="categorymembers",
            cmtitle="Category:" + place["commons_category"],
            cmtype="file",
            cmlimit="max",
        ):
            files.append(member.get("title", ""))
            if len(files) >= max_files:
                break
        if not files:
            continue
        for image in fetch_imageinfo(commons, files):
            from .schema import photo_resource_name

            photo_id = "commons:" + image["file"][5:]
            conn.execute(
                """
                INSERT INTO place_photos (place_id, id, name, url, description_url,
                                          width_px, height_px, author_name, license,
                                          position, source)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0, 'category')
                ON CONFLICT(place_id, id) DO NOTHING
                """,
                (
                    place["id"],
                    photo_id,
                    photo_resource_name(place["id"], photo_id),
                    image["url"],
                    image.get("description_url"),
                    image.get("width"),
                    image.get("height"),
                    image.get("artist"),
                    image.get("license"),
                ),
            )
            added += 1
        if log:
            log("%s: %d candidates" % (place["id"], len(files)))
    conn.commit()
    repair_attribution(conn)
    rank_photos(conn)
    return {"places": len(places), "added": added}
