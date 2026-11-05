<div align="center">

# placeswiki

**The open alternative to Google Places, for the places that don't move.**

Historical places and landmarks, with coordinates, descriptions and Wikimedia
photographs, served in the Google Places protocol from infrastructure you control.

[CI](https://github.com/thepeternemec/placeswiki/actions/workflows/ci.yml) ·
[API](docs/API.md) ·
[Integration](docs/INTEGRATION.md) ·
[Deploy](docs/DEPLOY.md) ·
[Data licence](DATA-LICENSE.md)

</div>

---

## Google charges rent on places it did not create

Every pan of a map, every detail panel, every photo is a billable request. The
terms also forbid storing what you fetched, so the cost never amortises: the
more successful your product, the more you pay for the same village church.

Meanwhile the church, its coordinates and forty photographs of it are already on
Wikipedia and Wikimedia Commons, under licences that permit redistribution.

placeswiki turns that into a database you own, and answers Google's endpoints
from it — so your existing client keeps working, and the meter stops.

## Self-host it

```console
$ git clone https://github.com/thepeternemec/placeswiki
$ cd placeswiki
$ python3 examples/fixture_db.py data/places.sqlite     # or build the real thing
$ docker build -t placeswiki .
$ docker run -d -p 8080:8080 -v "$PWD/data:/data" placeswiki
```

Put it behind TLS — Caddy, nginx, or your platform's load balancer — and it is a
service:

```console
$ curl https://places.yourdomain.com/health
{"status": "ok", "places": 500, "photos": 377, "google_linked": 0}
```

Recipes for Caddy, systemd, Fly.io and Render are in [docs/DEPLOY.md](docs/DEPLOY.md).
No account, no API key, no per-request cost. One SQLite file is the whole state.

## Point your app at it

Your client already speaks this protocol. Change the base URL:

```js
// before: const BASE = "https://places.googleapis.com";
const BASE = "https://places.yourdomain.com";

const response = await fetch(`${BASE}/v1/places:searchNearby`, {
  method: "POST",
  headers: {
    "Content-Type": "application/json",
    "X-Goog-FieldMask": "places.id,places.displayName,places.location,places.photos",
  },
  body: JSON.stringify({
    locationRestriction: {
      circle: { center: { latitude: 46.0503, longitude: 14.5045 }, radius: 500 },
    },
    maxResultCount: 20,
  }),
});
const { places } = await response.json();
```

| Endpoint | Google equivalent |
| --- | --- |
| `POST /v1/places:searchNearby` | Nearby Search (New) |
| `POST /v1/places:searchText` | Text Search (New) |
| `GET /v1/places/{id}` | Place Details (New) |

Field masks, nested paths, error envelopes and the 20-result cap behave as they
do upstream. The difference is what comes back: `wc:Q…` ids you own, Commons
photos with author and licence attached, and nothing that expires. If you
already store Google ids, `--prefer-google-ids` returns them where a link exists.

Full client examples in JavaScript, TypeScript and Python:
[docs/INTEGRATION.md](docs/INTEGRATION.md).

## Tell your stack when data changes

A reindex, a cache purge, a mobile bundle refresh — downstream systems should not
poll. Send a signed event after every build:

```console
$ placeswiki notify --db /data/places.sqlite \
    --url https://api.yourapp.com/hooks/places \
    --secret "$PLACESWIKI_WEBHOOK_SECRET"
```

The receiver verifies HMAC-SHA256 over the raw body, in
`X-Placeswiki-Signature`, the same convention Stripe and GitHub use:

```js
import { createHmac, timingSafeEqual } from "node:crypto";

export function verify(rawBody, header, secret) {
  const expected = "sha256=" + createHmac("sha256", secret).update(rawBody).digest("hex");
  return header.length === expected.length &&
    timingSafeEqual(Buffer.from(header), Buffer.from(expected));
}
```

A runnable receiver is in [examples/webhook_receiver.py](examples/webhook_receiver.py).

## Build the data

```console
$ pip install placeswiki
$ placeswiki bulk fetch  --db /data/places.sqlite --all-countries   # 2.2 M places
$ placeswiki bulk enrich --db /data/places.sqlite --limit 500
$ placeswiki engine resolve --db /data/places.sqlite                # Wikidata ids
$ placeswiki photos --db /data/places.sqlite --rank --category      # scored photos
$ placeswiki slim    --db /data/places.sqlite --out /data/serve.sqlite
```

| Command | What it does |
| --- | --- |
| `collect` | crawl by category, links, or a geo grid that survives the 500-result cap |
| `bulk` | stage every Wikidata item with a heritage designation and coordinates |
| `engine` | resolve articles to Wikidata ids, claims and lead images |
| `photos` | resolve, score, rank and expand photographs |
| `link` | attach Google place ids with method, confidence and evidence |
| `publish` | a verifiable bundle: payload, photos, attribution, SHA-256 |
| `serve` | the Places protocol, from your database |
| `notify` | signed webhook when the dataset changes |
| `gaps` | what is missing upstream, linked to Wikidata |

## Photo intelligence, not photo scraping

Every photograph is scored 0–100 and the reasons are stored beside the score:

```
resolution 40 · licence 25 · attribution 15 · lead image 20
```

```console
$ placeswiki engine best --db /data/places.sqlite --place wc:Q10285
commons:Colosseo 2020.jpg  score 89.0
  - 12051x8442 → 40/40 resolution
  - CC BY-SA 4.0 → 14/25 licence
  - author present → 15/15 attribution
  - lead image (P18) → 20/20
```

That is the part Google cannot give you at any price: not a photo, but a
defensible choice of photo, with the attribution that makes using it lawful.

## Honest scope

Heritage, monuments, landmarks. No restaurants, opening hours, ratings or phone
numbers — they churn, they are commercial, and Wikimedia does not track them.
A narrow dataset that is true beats a broad one that is stale.

Coverage follows volunteer effort and is uneven by country. This project never
writes to Wikimedia; `gaps` turns what is missing into a work list for human
editors, who fix it upstream where every downstream user benefits.

## Licence

Code MIT. Text CC BY-SA 4.0 from Wikipedia. Photographs per file, attributed.
Google place ids under Google's terms, which permit storing that field.
Fields this project generates are CC0.

Content by Wikimedia contributors. Identifiers by Google. Schema by placeswiki.
