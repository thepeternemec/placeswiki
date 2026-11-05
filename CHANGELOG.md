# Changelog

Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
Versioning: [Semantic Versioning](https://semver.org/).

## [3.4.1] — 2026-11-06

### Fixed

- **A 3.3 database could not be opened by 3.4.** `ensure_schema` created an index
  on `name_folded` before the column existed, so opening a file built by the
  previous release failed with `no such column`. Column migrations now run before
  the DDL. Verified by upgrading the 3.3 release database in place and backfilling
  all 500 rows.

## [3.4.0] — 2026-11-06

Found by running the pipeline end to end against live Wikidata and serving the
result under concurrent load.

### Added

- **Photo media endpoint**: `GET /v1/{photo_name}/media` answers `302` with the
  Wikimedia URL, `Cache-Control` and CORS. Before this, clients received photo
  resource names they had no way to resolve — the API could describe a photo but
  not deliver it.
- **Accent-insensitive text search**: `Kunsperk` now finds `Kunšperk`. A
  `name_folded` column (NFKD, combining marks stripped, casefolded) is written by
  `normalize` and `bulk`, backfilled by `slim` for older databases, and queried
  by `searchText`.

### Fixed

- **Server died under concurrency.** The stdlib listen backlog of 5 dropped
  connections, and one SQLite connection was shared across request threads.
  Connections are now thread-local, the backlog is 128, and handler exceptions
  return a 500 JSON envelope instead of closing the socket.
- **HTML in author names**, again: `bulk enrich` wrote the raw Commons artist
  field, so `<a href=…>` reached `authorAttributions`. Cleaning now happens at
  write time, and ranking persists the cleaned value.

## [3.3.0] — 2026-11-05

### Added

- **Project website** in `site/` — a static page in Wikipedia's visual grammar:
  serif headings, quiet rules, blue links, an infobox, no build step and no
  JavaScript. Deployed to GitHub Pages on every push; Vercel-ready via
  `vercel.json` (`outputDirectory: site`).
- `pages` workflow and a one-click Vercel deploy button.

## [3.2.0] — 2026-11-05

### Added

- **`notify`**: signed webhook after a build or publish, so search indexes, CDN
  caches and mobile bundles refresh instead of polling. HMAC-SHA256 over the raw
  body in `X-Placeswiki-Signature`; retries 5xx, not 4xx.
- **`docs/INTEGRATION.md`**: base-URL swap, JS/TS and Python clients, field mask
  usage, what differs from Google and how to handle it, migration sequence.
- **`docs/DEPLOY.md`**: Docker, Caddy, nginx, systemd, Fly/Render, sizing,
  updates, backups, caching.
- **`examples/client.py`** and **`examples/webhook_receiver.py`**: a stdlib
  client and a receiver that rejects bad signatures with a 401.

### Changed

- README rewritten for people running this in production: self-hosting first,
  a real hostname instead of `127.0.0.1` in the hero, and the webhook in the
  main flow.

## [3.1.0] — 2026-11-05

### Added

- **Photo intelligence** (`intel.py`): explainable scoring — resolution 40,
  licence 25, attribution 15, lead image 20 — stored with the reasons, plus
  `photos --rank`, `--category` (expand a thin set from the Commons category,
  marked `source='category'`) and `--repair` (strip HTML from attribution).
- **Place identity engine** (`engine.py`): resolves a Wikipedia article to its
  Wikidata item in batches of 50, then adopts coordinates, `P1435`, `P373` and
  `P18`. `engine lookup` finds candidates by name and distance; `engine best`
  explains the chosen photograph.
- **Dockerfile**: unprivileged image, mounted SQLite file, health check.
- **docs/ARCHITECTURE.md**: stages, layers and the identity/photo rules.
- **CI `e2e` job**: builds a fixture database offline, publishes it, parses the
  payload with `google.maps.places_v1`, then serves it and queries over HTTP.

### Fixed

- Bulk enrichment stored **raw HTML in author names** (`<a href=…>`), which would
  have leaked into `authorAttributions`. `photos --repair` fixed 346 existing
  rows in the Slovenian sample; the clean-up is now part of ranking.
- Wikidata's `P373` now takes precedence over a crawled Commons category, as the
  more canonical value.

## [3.0.0] — 2026-10-22

### Changed

- **Renamed from `placelore` to `placeswiki`.** Module, console script and
  repository. Version 3.0.0; GitHub redirects the previous URL.
- Tagline is now the thing people search for: *Google Places, from the wiki.*

### Fixed

Deep testing against live APIs found five defects, all fixed with regression
tests:

- **The link crawler only ever returned its seed.** `prop=links` nests results as
  `query.pages[].links[]`, which the generic paginator does not flatten; crawling
  by `--seed` fetched 1 page instead of 10.
- `link remove` and `link promote` raised a traceback instead of a message.
- `collect --lat` without `--lon` silently did nothing.
- `bulk --endpoint` with an unknown endpoint raised a traceback.
- `serve` with a missing database raised a traceback.

## [2.0.0] — 2026-10-22

### Changed

- **Renamed from `wikicrawl` to `placelore`.** The old name described the
  mechanism; this one describes the thing. Breaking for anyone who pinned the
  package: the module, the console script and the repository are all
  `placelore` now. GitHub redirects the old repository URL; old releases stay
  available under the previous name and version.
- README rewritten: what it answers, what it holds, what it is not. Fewer tables,
  no feature inventory.

## [Unreleased]

- `overture` importer for breadth (3.17 M Cultural and Historic features)
- `bulk run` that drains `pending` in one command
- Sharded bundles under 100 MB for static hosting

## [1.1.0] — 2026-10-22

### Added

- **`serve`**: Nearby Search, Text Search and Place Details under Google's paths,
  from a local SQLite file. Honours `X-Goog-FieldMask` including nested paths,
  returns Google's error envelope, caps at 20 nearest-first, and can return linked
  Google ids as `id` with `--prefer-google-ids`.
- **`slim`**: the read-only serving database — provenance, categories, infobox
  JSON and bookkeeping dropped. 940 KB → 300 KB on the sample.
- **`docs/API.md`**: base-URL swap, endpoint support, deliberate differences.

## [1.0.0] — 2026-10-22

### Added

- **`gaps`**: missing photographs, categories, articles, designations,
  attribution and licences, each linked to Wikidata. Markdown and JSON; counts
  complete, rows capped.
- Own section on giving back to Wikimedia in the docs.

### Changed

- Actions bumped to `checkout@v7`, `setup-python@v7`, `action-gh-release@v3`.
- Release workflow builds, installs and imports the wheel before publishing.

## [0.3.0] — 2026-10-21

- **`bulk`**: stage every Wikidata item with `P1435` + `P625` (2,210,883) via
  SPARQL only, then enrich by `P18` in batches of 50. Resumable.
- **`publish`**: bundle with payload, photo index, generated `ATTRIBUTION.md` and
  a Frictionless `datapackage.json` carrying SHA-256 per file.
- **`link`**: `place_links` keeps every Google candidate with method,
  confidence and evidence; one primary per place; import/export/check/promote/remove.
- **`verify`**: parse the payload with `google.maps.places_v1`; enforced in CI.
- Fixed: fabricated `businessStatus`, shared-photo key collision, `zoo` and
  `art_gallery` inference from template noise.

## [0.2.0] — 2026-10-21

- Google Places (New) shaped `places` and `place_photos`, strict serialisers that
  omit unset fields as protobuf JSON does.
- `google-match` with name and distance scoring; only `google_place_id` stored by
  default; `v_google_stale` for refresh.

## [0.1.0] — 2026-10-21

- Polite MediaWiki client: user agent, `maxlag`, `Retry-After`, backoff,
  continuation paging.
- Category, link and geo-grid crawling; resumable SQLite store; Commons
  `imageinfo` with licence and author preserved.
