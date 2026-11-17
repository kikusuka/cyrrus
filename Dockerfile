# Cyrrus gateway container.
#
# Single stage: python:3.13-slim plus the pinned PyPI package.  There is no
# compiler/toolchain stage because Cyrrus's core has no third-party
# dependencies.
#
# Build (CYRRUS_VERSION is required; there is no "latest" default):
#   docker build --build-arg CYRRUS_VERSION=0.3.0b6 -t cyrrus:0.3.0b6 .
#
# Default run (safe: the gateway stays on 127.0.0.1 inside the container and is
# not reachable from the host; /data is a fresh named volume):
#   docker run --rm -v cyrrus-data:/data cyrrus:0.3.0b6
#
# Public run on this machine only (the tested configuration):
#   1. Copy docs/docker.config.example.json to a private directory.
#   2. Set gateway.host to "0.0.0.0" and gateway.api_key_env to the NAME of an
#      environment variable, e.g. CYRRUS_GATEWAY_TOKEN.
#   3. Set provider.api_key_env to the NAME of the OUTGOING provider key
#      variable, e.g. OPENAI_API_KEY (or remove the provider key for a local
#      provider).
#   4. Run, binding the published port to host loopback:
#      docker run --rm --name cyrrus \
#        -p 127.0.0.1:8787:8787 \
#        -v cyrrus-data:/data \
#        -v "$PWD/cyrrus.config.json:/data/cyrrus.config.json:ro" \
#        -e CYRRUS_GATEWAY_TOKEN=replace-with-a-long-random-token \
#        -e OPENAI_API_KEY=replace-with-the-provider-key \
#        cyrrus:0.3.0b6
#
#   5. Call it with the incoming token:
#      curl -H "Authorization: Bearer $CYRRUS_GATEWAY_TOKEN" \
#        http://127.0.0.1:8787/cyrrus/status
#
# The bind above is host-loopback only.  For real hosting, terminate TLS in a
# reverse proxy (Caddy, nginx, Traefik) and let the proxy reach the container;
# do not publish the plain-HTTP port directly to the internet.
#
# gateway.api_key_env protects INCOMING requests.  provider.api_key_env is a
# different setting: it names the OUTGOING key Cyrrus sends to the model
# provider.  The container never logs either value.

FROM python:3.13-slim

# Required; an empty value stops the build instead of silently installing
# whatever happens to be newest.
ARG CYRRUS_VERSION
RUN if [ -z "$CYRRUS_VERSION" ]; then \
        echo "CYRRUS_VERSION build arg is required (e.g. 0.3.0b6)" >&2; \
        exit 1; \
    fi

# Install the exact PyPI release into the system environment.
RUN python -m pip install --no-cache-dir "cyrrus==${CYRRUS_VERSION}"

# Non-root runtime user.  UID/GID 1000 matches the conventional first user on
# Linux hosts, so a bind-mounted data directory is writable without chown.
# /data is created and owned before USER, so a fresh named volume inherits that
# ownership and cyrrus can create the SQLite database there.
RUN groupadd --gid 1000 cyrrus \
    && useradd --uid 1000 --gid 1000 --create-home --home-dir /home/cyrrus \
        --shell /usr/sbin/nologin cyrrus \
    && mkdir -p /data \
    && chown cyrrus:cyrrus /data

VOLUME ["/data"]
EXPOSE 8787

USER cyrrus
WORKDIR /home/cyrrus

# Python-only healthcheck (the slim image has no curl).  It reads the mounted
# config, and if gateway.api_key_env is set it sends that token, so it works
# whether /health is public or authenticated in the installed release.
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD ["python", "-c", "import json, os, urllib.request; p='/data/cyrrus.config.json'; c=json.load(open(p)) if os.path.exists(p) else {}; g=c.get('gateway', {}); e=g.get('api_key_env'); r=urllib.request.Request('http://127.0.0.1:%d/health' % g.get('port', 8787)); t=os.environ.get(e) if e else None; r.add_header('Authorization', 'Bearer ' + t) if t else None; urllib.request.urlopen(r, timeout=3)"]

# Exec form, so the cyrrus process is PID 1 and receives signals directly.
# STOPSIGNAL SIGINT uses the gateway's existing Ctrl+C path: it stops accepting
# requests, drains pending record_turn work (gateway.shutdown_timeout, 30 s by
# default), then exits.  Use `docker stop --timeout 40` if a large backlog may
# need the full drain budget.
STOPSIGNAL SIGINT
CMD ["cyrrus", "serve", "--config", "/data"]
