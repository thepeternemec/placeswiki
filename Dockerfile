# placeswiki — a Places endpoint backed by a SQLite file.
#
#   docker build -t placeswiki .
#   docker run -p 8080:8080 -v "$PWD/data:/data" placeswiki
#
# Mount a slim database at /data/places.sqlite, or build one inside the image
# with: docker run --rm -v "$PWD/data:/data" placeswiki \
#          placeswiki bulk fetch --db /data/places.sqlite --country Q215

FROM python:3.12-slim

WORKDIR /app
COPY pyproject.toml README.md ./
COPY placeswiki ./placeswiki
RUN pip install --no-cache-dir .

RUN useradd --create-home --uid 10001 places \
    && mkdir -p /data && chown places /data
USER places

ENV PLACESWIKI_DB=/data/places.sqlite
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8080/health', timeout=3).status==200 else 1)"

ENTRYPOINT ["sh", "-c", "placeswiki serve --db \"$PLACESWIKI_DB\" --host 0.0.0.0 --port 8080"]
