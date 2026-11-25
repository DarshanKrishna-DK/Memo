# syntax=docker/dockerfile:1
# Memo production image: React SPA (built here) + FastAPI + in-process job worker. See docs/DEPLOY_RENDER.md.

# ---- 1. build the web app -------------------------------------------------------------------------------------
FROM node:20-slim AS web
WORKDIR /web
COPY web/package.json web/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY web/ ./
RUN npm run build

# ---- 2. runtime -----------------------------------------------------------------------------------------------
FROM python:3.12-slim AS runtime
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
# ffmpeg (with libass) renders reels; fonts-noto-core carries Devanagari + Kannada, fonts-dejavu the Latin fallback.
RUN apt-get update \
 && apt-get install -y --no-install-recommends ffmpeg fonts-noto-core fonts-dejavu-core \
 && rm -rf /var/lib/apt/lists/* \
 && test -f /usr/share/fonts/truetype/noto/NotoSansDevanagari-Regular.ttf \
 && test -f /usr/share/fonts/truetype/noto/NotoSansKannada-Regular.ttf \
 && useradd --system --create-home --uid 10001 memo

WORKDIR /app
COPY backend/requirements.txt backend/requirements.txt
# test-only packages are not needed at runtime
RUN grep -v -i '^pytest' backend/requirements.txt > /tmp/req.txt && pip install -r /tmp/req.txt && rm /tmp/req.txt
COPY backend/ backend/
COPY --from=web /web/dist web/dist
COPY docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
RUN chmod +x /usr/local/bin/docker-entrypoint.sh && mkdir -p /app/data && chown -R memo:memo /app/data

WORKDIR /app/backend
ENV PORT=10000 STORAGE_DIR=/app/data/storage GALLERY_DIR=/app/data/gallery
EXPOSE 10000
# Starts as root only to fix ownership of the mounted disk, then drops to the unprivileged `memo` user.
ENTRYPOINT ["docker-entrypoint.sh"]
CMD ["sh", "-c", "exec python -m uvicorn app.main:app --host 0.0.0.0 --port ${PORT} --proxy-headers --forwarded-allow-ips='*'"]
