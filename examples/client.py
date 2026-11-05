#!/usr/bin/env python3
"""Call a placeswiki server with the standard library only.

PLACES_BASE_URL=https://places.yourdomain.com python3 examples/client.py
"""

import json
import os
import urllib.request

BASE = os.environ.get("PLACES_BASE_URL", "http://127.0.0.1:8080")


def nearby(lat, lon, radius=500, fields="places.id,places.displayName,places.location"):
    request = urllib.request.Request(
        BASE + "/v1/places:searchNearby",
        data=json.dumps(
            {
                "locationRestriction": {
                    "circle": {"center": {"latitude": lat, "longitude": lon}, "radius": radius}
                },
                "maxResultCount": 20,
            }
        ).encode(),
        headers={"Content-Type": "application/json", "X-Goog-FieldMask": fields},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=10) as response:
        return json.loads(response.read()).get("places", [])


if __name__ == "__main__":
    for place in nearby(46.0503, 14.5045):
        print(place["id"], "-", place["displayName"]["text"])
