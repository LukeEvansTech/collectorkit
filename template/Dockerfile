# syntax=docker/dockerfile:1@sha256:572cebbc2b15e6f84c077742952674889cb63cd5e9b80abdffcbe587b6f19183
FROM python:3.15-slim-bookworm@sha256:498829c717b1e59fc42f0e7865eafe4e04ca0f70a3769d4ae70ba218df54507c

# App version, stamped from the release tag by CI (docker-publish.yml build-args).
ARG VERSION=0.0.0-dev
ENV APP_VERSION=${VERSION} \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    MYAPP_DATA=/data \
    HOME=/tmp

LABEL org.opencontainers.image.source="https://github.com/LukeEvansTech/myapp" \
      org.opencontainers.image.title="myapp" \
      org.opencontainers.image.description="What it collects, in one line" \
      org.opencontainers.image.version="${VERSION}"

WORKDIR /app
COPY requirements.txt ./
# git: pip installs collectorkit from its tag. curl: the feed collectors use it when present,
# because some shops refuse Python's TLS stack. Not version-pinned: the base image digest fixes
# the Debian release, and a pinned point version vanishes from the mirror after a security update.
# An app that renders pages also needs the obscura binary on PATH; an app that drives a browser
# itself installs Playwright here instead (see sakuga's Dockerfile).
# hadolint ignore=DL3008
RUN apt-get update && apt-get install -y --no-install-recommends curl git \
    && pip install --no-cache-dir -r requirements.txt \
    && apt-get purge -y git && apt-get autoremove -y \
    && rm -rf /var/lib/apt/lists/*

COPY myapp ./myapp

RUN mkdir -p /data && chown -R 65532:65532 /data
VOLUME ["/data"]

USER 65532:65532
# Kubernetes probes own liveness (/health); an image healthcheck would double-probe.
HEALTHCHECK NONE
EXPOSE 8080
ENTRYPOINT ["python", "-m", "myapp"]
CMD ["serve"]
