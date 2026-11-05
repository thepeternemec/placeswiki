# Deploy

The server is a read-only SQLite connection behind a threaded HTTP server. It
needs one file, one port and TLS in front of it.

## Docker

```console
$ docker build -t placeswiki .
$ docker run -d --name places \
    -p 8080:8080 \
    -v "$PWD/data:/data" \
    -e PLACESWIKI_WEBHOOK_SECRET=change-me \
    placeswiki
```

The image runs as uid 10001, reads `/data/places.sqlite`, exposes `/health`, and
writes nothing except its own logs.

## Caddy (TLS in one line)

```caddyfile
places.yourdomain.com {
    reverse_proxy 127.0.0.1:8080
    encode zstd gzip
}
```

## nginx

```nginx
server {
    server_name places.yourdomain.com;
    location / {
        proxy_pass http://127.0.0.1:8080;
        proxy_set_header Host $host;
        proxy_read_timeout 15s;
    }
    listen 443 ssl http2;
    # certificates via certbot or your platform
}
```

## systemd

```ini
[Unit]
Description=placeswiki
After=network.target

[Service]
User=places
WorkingDirectory=/srv/placeswiki
ExecStart=/srv/placeswiki/.venv/bin/placeswiki serve --db /srv/data/places.sqlite --host 127.0.0.1 --port 8080
Restart=on-failure

[Install]
WantedBy=multi-user.target
```

## Fly.io / Render / Railway

1. Deploy the Dockerfile; set the internal port to `8080`.
2. Mount a volume at `/data`.
3. Build the database once with a one-off command:
   `placeswiki bulk fetch --db /data/places.sqlite --country Q215`
   then `placeswiki slim --db /data/places.sqlite --out /data/serve.sqlite`.
4. Point the service at the slim file via `PLACESWIKI_DB=/data/serve.sqlite`.
5. Add a health check on `/health`.

## Sizing

| Data | Slim database | Memory |
| --- | --- | --- |
| 500 places | 268 KB | ~40 MB |
| 100 000 places | ~55 MB | ~120 MB |
| 2 200 000 places | ~1.2 GB | ~600 MB |

The server keeps SQLite's page cache in memory; the figure above is a ceiling,
not a requirement. Queries are bounding-box scans over an index, so latency is
dominated by disk on cold start and by the network thereafter.

## Updating data

```console
$ placeswiki bulk fetch  --db /data/places.sqlite --all-countries
$ placeswiki bulk enrich --db /data/places.sqlite --limit 5000
$ placeswiki photos      --db /data/places.sqlite --rank --category
$ placeswiki slim        --db /data/places.sqlite --out /data/serve.sqlite
$ placeswiki notify      --db /data/places.sqlite \
    --url https://api.yourapp.com/hooks/places --secret "$SECRET"
$ systemctl reload places
```

Run it from cron or a scheduled job. `bulk` and `photos` are resumable, so a run
that dies at 60% continues rather than restarting.

## Backups

The database is a file. Copy it while the service is idle, or use
`sqlite3 /data/places.sqlite ".backup /backups/places-$(date +%F).sqlite"` for a
consistent snapshot under load.

## Caching

Responses are cheap but not free. Put a CDN in front of `GET /v1/places/{id}`
with a long TTL — place data changes monthly at most — and leave the POST
endpoints uncached.
