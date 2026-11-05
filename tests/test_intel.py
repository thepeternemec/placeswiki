"""Tests for photo scoring and the Wikimedia identity engine."""

from __future__ import annotations

import json
import sqlite3
import unittest
from unittest.mock import patch

from placeswiki.engine import enrich_from_wikidata, lookup, resolve_titles
from placeswiki.intel import (
    best_photo,
    clean_author,
    collect_category_photos,
    ensure_intel_schema,
    rank_photos,
    repair_attribution,
    score_photo,
)
from placeswiki.schema import ensure_schema


class DB(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        ensure_schema(self.conn)
        ensure_intel_schema(self.conn)
        self.conn.execute(
            "INSERT INTO places (id, name, lat, lng, types, wikipedia_url, commons_category)"
            " VALUES ('wc:enwiki:1', 'Test Place', 46.0, 14.5, '[]',"
            " 'https://en.wikipedia.org/wiki/Test_Place', 'Test Place')"
        )
        self.conn.commit()

    def tearDown(self):
        self.conn.close()

    def add_photo(self, photo_id, width, height, license_name, author, source="p18"):
        self.conn.execute(
            "INSERT INTO place_photos (place_id, id, name, url, width_px, height_px,"
            " license, author_name, source) VALUES ('wc:enwiki:1', ?, ?, 'https://u/x',"
            " ?, ?, ?, ?, ?)",
            (photo_id, "places/wc:enwiki:1/photos/x", width, height, license_name, author, source),
        )
        self.conn.commit()


class TestScoring(unittest.TestCase):
    def test_bigger_beats_smaller(self):
        big, _ = score_photo(6000, 4000, "CC BY-SA 4.0", "A")
        small, _ = score_photo(640, 480, "CC BY-SA 4.0", "A")
        self.assertGreater(big, small)

    def test_licence_ordering(self):
        cc0, _ = score_photo(2000, 2000, "CC0", "A")
        by, _ = score_photo(2000, 2000, "CC BY 4.0", "A")
        by_sa, _ = score_photo(2000, 2000, "CC BY-SA 4.0", "A")
        gfdl, _ = score_photo(2000, 2000, "GFDL", "A")
        self.assertGreater(cc0, by)
        self.assertGreater(by, by_sa)
        self.assertGreater(by_sa, gfdl)

    def test_author_and_lead_bonuses(self):
        without, _ = score_photo(3000, 2000, "CC BY 4.0", "")
        with_author, _ = score_photo(3000, 2000, "CC BY 4.0", "Jane")
        lead, _ = score_photo(3000, 2000, "CC BY 4.0", "Jane", is_lead=True)
        self.assertGreater(with_author, without)
        self.assertGreater(lead, with_author)

    def test_maximum_is_one_hundred(self):
        score, reasons = score_photo(9000, 9000, "CC0", "Jane", is_lead=True)
        self.assertEqual(score, 100.0)
        self.assertTrue(any("lead image" in reason for reason in reasons))

    def test_reasons_are_readable(self):
        _score, reasons = score_photo(4000, 3000, "CC0", "Jane")
        self.assertTrue(any("resolution" in r for r in reasons))
        self.assertTrue(any("licence" in r for r in reasons))
        self.assertTrue(any("attribution" in r for r in reasons))


class TestRanking(DB):
    def test_rank_orders_and_scores(self):
        self.add_photo("commons:small.jpg", 640, 480, "GFDL", "")
        self.add_photo("commons:big.jpg", 5000, 4000, "CC0", "Jane")
        result = rank_photos(self.conn)
        self.assertEqual(result["ranked"], 2)
        best = best_photo(self.conn, "wc:enwiki:1")
        self.assertEqual(best["id"], "commons:big.jpg")
        self.assertEqual(best["position"], 0)
        self.assertTrue(json.loads(best["score_reasons"]))

    def test_repair_attribution_strips_html(self):
        self.add_photo(
            "commons:x.jpg",
            1000,
            1000,
            "CC0",
            '<a href="//commons.wikimedia.org/wiki/User:Jane">Jane</a>',
        )
        result = repair_attribution(self.conn)
        self.assertEqual(result["repaired"], 1)
        row = self.conn.execute("SELECT author_name, author_uri FROM place_photos").fetchone()
        self.assertEqual(row["author_name"], "Jane")
        self.assertEqual(row["author_uri"], "https://commons.wikimedia.org/wiki/User:Jane")

    def test_clean_author_handles_plain_text(self):
        self.assertEqual(clean_author("Jane Doe"), ("Jane Doe", ""))


class FakeCommons:
    def paginate(self, **params):
        for index in range(3):
            yield {"title": "File:Candidate %d.jpg" % index}


class TestCategoryExpansion(DB):
    def test_adds_candidates_and_ranks(self):
        images = [
            {
                "file": "File:Candidate %d.jpg" % i,
                "url": "https://u/%d.jpg" % i,
                "width": 3000,
                "height": 2000,
                "license": "CC BY-SA 4.0",
                "artist": "Jane",
                "description_url": "https://c/%d" % i,
            }
            for i in range(3)
        ]
        with patch("placeswiki.images.fetch_imageinfo", return_value=iter(images)):
            result = collect_category_photos(self.conn, FakeCommons(), limit_places=1)
        self.assertEqual(result["added"], 3)
        self.assertEqual(
            self.conn.execute(
                "SELECT COUNT(*) FROM place_photos WHERE source='category'"
            ).fetchone()[0],
            3,
        )
        self.assertEqual(
            self.conn.execute("SELECT COUNT(*) FROM place_photos WHERE score IS NULL").fetchone()[
                0
            ],
            0,
        )


class FakeWikidata:
    def __init__(self, entities):
        self.entities = entities
        self.calls = []

    def get(self, params=None, **kwargs):
        params = dict(params or {})
        params.update(kwargs)
        self.calls.append(params)
        if params.get("action") == "wbsearchentities":
            return {"search": [{"id": qid} for qid in self.entities]}
        if params.get("action") == "wbgetentities":
            if "ids" in params:
                ids = params["ids"].split("|")
            else:
                ids = list(self.entities)
            return {"entities": {qid: self.entities[qid] for qid in ids if qid in self.entities}}
        return {}


def entity(lat, lon, heritage=None, category="", image=""):
    claims = {"P625": [{"mainsnak": {"datavalue": {"value": {"latitude": lat, "longitude": lon}}}}]}
    if heritage:
        claims["P1435"] = [{"mainsnak": {"datavalue": {"value": {"id": heritage}}}}]
    if category:
        claims["P373"] = [{"mainsnak": {"datavalue": {"value": category}}}]
    if image:
        claims["P18"] = [{"mainsnak": {"datavalue": {"value": image}}}]
    return {
        "claims": claims,
        "sitelinks": {"enwiki": {"title": "Test Place"}},
        "labels": {"en": {"value": "Test Place"}},
        "descriptions": {"en": {"value": "a place"}},
    }


class TestEngine(DB):
    def test_resolve_titles_maps_sitelinks(self):
        api = FakeWikidata({"Q42": entity(46.0, 14.5, "Q1", "Cat", "Img.jpg")})
        records = resolve_titles(api, ["Test Place"])
        self.assertIn("Test Place", records)
        self.assertEqual(records["Test Place"]["qid"], "Q42")
        self.assertEqual(records["Test Place"]["heritage"], ["Q1"])

    def test_enrich_fills_qid_heritage_and_lead_image(self):
        api = FakeWikidata({"Q42": entity(46.0, 14.5, "Q1", "Cat", "Img.jpg")})
        result = enrich_from_wikidata(self.conn, api)
        self.assertEqual(result["resolved"], 1)
        self.assertEqual(result["photos"], 1)
        row = self.conn.execute(
            "SELECT wikidata_id, heritage_designations, commons_category FROM places"
        ).fetchone()
        self.assertEqual(row["wikidata_id"], "Q42")
        self.assertEqual(json.loads(row["heritage_designations"]), ["Q1"])
        self.assertEqual(row["commons_category"], "Cat")

    def test_enrich_is_idempotent(self):
        api = FakeWikidata({"Q42": entity(46.0, 14.5)})
        enrich_from_wikidata(self.conn, api)
        second = enrich_from_wikidata(self.conn, api)
        self.assertEqual(second["places"], 0)

    def test_lookup_filters_far_candidates(self):
        api = FakeWikidata(
            {
                "Q1": entity(46.0005, 14.5005),
                "Q2": entity(48.0, 16.0),
            }
        )
        results = lookup(api, "Test Place", 46.0, 14.5, max_km=1.0)
        self.assertEqual([r["qid"] for r in results], ["Q1"])
        self.assertLess(results[0]["distance_km"], 0.2)


if __name__ == "__main__":
    unittest.main()
