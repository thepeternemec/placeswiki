# Integrate

Everything here is written for a developer who already has a Places client and
wants to stop renting it.

## 1. Swap the base URL

| Google | placeswiki |
| --- | --- |
| `https://places.googleapis.com` | `https://places.yourdomain.com` |

Paths, bodies, headers and the response envelope are unchanged. The API key
header is accepted and ignored — remove it, or keep it for your own gateway.

## 2. JavaScript / TypeScript

```ts
const BASE = process.env.PLACES_BASE_URL!;

export type Place = {
  id: string;
  displayName?: { text: string; languageCode: string };
  location?: { latitude: number; longitude: number };
  photos?: { name: string }[];
};

export async function nearby(lat: number, lon: number, radius = 500): Promise<Place[]> {
  const response = await fetch(`${BASE}/v1/places:searchNearby`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "X-Goog-FieldMask": "places.id,places.displayName,places.location,places.photos",
    },
    body: JSON.stringify({
      locationRestriction: { circle: { center: { latitude: lat, longitude: lon }, radius } },
      maxResultCount: 20,
    }),
  });
  if (!response.ok) throw new Error(`placeswiki ${response.status}`);
  return (await response.json()).places ?? [];
}
```

Fetch the image from the `photos[].name` resource name:

```ts
const src = `${BASE}/v1/${place.photos![0].name}/media`;   // 302 -> Wikimedia URL
```

The redirect lands on the Commons upload URL, so the licence and author are the
ones recorded alongside it. If you ship a static bundle instead of a server, the
same mapping is in `photos.json`.

## 3. Python

```python
import os, requests

BASE = os.environ["PLACES_BASE_URL"]


def nearby(lat, lon, radius=500):
    response = requests.post(
        f"{BASE}/v1/places:searchNearby",
        headers={"X-Goog-FieldMask": "places.id,places.displayName,places.location"},
        json={
            "locationRestriction": {
                "circle": {"center": {"latitude": lat, "longitude": lon}, "radius": radius}
            },
            "maxResultCount": 20,
        },
        timeout=10,
    )
    response.raise_for_status()
    return response.json().get("places", [])
```

The standard library works too — see `examples/client.py`.

## 4. Place details and text search

```console
$ curl "https://places.yourdomain.com/v1/places/wc:Q10285" \
    -H "X-Goog-FieldMask: id,displayName,location,photos"

$ curl -X POST "https://places.yourdomain.com/v1/places:searchText" \
    -H "Content-Type: application/json" \
    -d '{"textQuery":"Colosseum","pageSize":5}'
```

## 5. What differs, and how to handle it

| Difference | Handling |
| --- | --- |
| `id` is `wc:…`, not `ChIJ…` | store it as-is; it is stable |
| you already store Google ids | run `google-match`, then `serve --prefer-google-ids` |
| no `pageToken` | results are nearest-first, capped at 20 — widen the radius instead |
| no ratings, hours, phone | keep Google for those, or drop the field |
| photo `name` is a resource name | resolve it via `photos.json` |
| no API key | do not forward `X-Goog-Api-Key` to a browser |

Your error handling already works: `{"error": {"code": 400, "status":
"INVALID_ARGUMENT", "message": "…"}}`.

## 6. Keep it in sync

After `bulk` / `photos` / `slim`, notify your services:

```console
$ placeswiki notify --db /data/places.sqlite \
    --url https://api.yourapp.com/hooks/places \
    --secret "$PLACESWIKI_WEBHOOK_SECRET"
```

Payload:

```json
{
  "event": "dataset.updated",
  "dataset": {"places": 500, "photos": 377, "google_linked": 0},
  "source": "placeswiki/3.2.0",
  "generated_at": "2026-11-05T20:34:22Z"
}
```

`X-Placeswiki-Signature: sha256=<hex>` is HMAC-SHA256 over the exact body.
Verify before parsing; reject on mismatch. Retries: 5xx and connection errors are
retried three times, 4xx is not.

## 7. Migrating an existing product

1. Run `google-match --dry-run` to see what would link, then for real on the
   subset you serve.
2. Deploy placeswiki next to your current provider.
3. Feature-flag the base URL per environment.
4. Compare `google_matches.confidence` against your own acceptance bar.
5. Move historical places first; keep Google for restaurants and live status.

Most teams find the heritage data is the long tail that was costing the most and
changing the least.
