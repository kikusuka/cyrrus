# Sphinx: a small, secure Docker image for hosting cyrrus.
#
# Build:
#   docker build -t ghcr.io/kikusuka/cyrrus:VERSION .
#
# Run (loopback-only, no network exposure by default):
#   docker run --rm -v cyrrus-data:/data ghcr.io/kikusuka/cyrrus:VERSION cyrrus --config /data/config.json serve
#
# To expose the gateway on a host port, configure an api_key_env in the config
# and map the port manually, e.g.:
#   docker run --rm -p 8787:8787 -v cyrrus-data:/data \
#     ghcr.io/kikusuka/cyrrus:VERSION cyrrus --config /data/config.json serve
#
# The image runs as non-root user uid=1000, gid=1000.
# A data directory volume (/data) persists config and memory db.

FROM python:3.13-slim AS builder

# Install build dependencies (no recommended packages to keep image small).
RUN apt-get update -y && \
    apt-get install -y --no-install-recommends \
        ca-certificates \
        git \
    && rm -rf /var/lib/apt/lists/*

# Install uv and pin Python 3.13 (uv supplies a shared libpython required by PyInstaller).
ENV UV_VERSION=0.13.8
RUN curl -fLsSf "https://astral.sh/uv/install.sh" | sh

# Create a non-root user before installing the app.
# Group 1000 may not exist yet in the base image; create it if needed.
RUN groupadd -f -g 1000 cyrrus || true && \
    useradd -m -u 1000 -g cyrrus cyrrus

# Install cyrrus from PyPI (pre-release allowed) into the user's tool directory.
# The uv installer respects the current user, so it installs to the cyrrus user's
# ~/.local/bin.  We switch to the cyrrus user before running it.
USER cyrrus
ENV PATH="/home/cyrrus/.local/bin:$PATH"
RUN uv tool install --prerelease allow cyrrus

# ---- Runtime stage ----
FROM python:3.13-slim

# Minimal runtime deps (curl needed so uv can download Python if desired).
RUN apt-get update -y && \
    apt-get install -y --no-install-recommends \
        ca-certificates \
        curl \
    && rm -rf /var/lib/apt/lists/*

# Create the same non-root user (uid=1000) so volumes owned by it survive restarts.
# Do this as root first, then switch to the new user.
RUN groupadd -f -g 1000 cyrrus || true && \
    useradd -m -u 1000 -g cyrrus cyrrus

# Install uv (runtime needs it for tool management).
# The uv installer respects the current user, so it installs to the cyrrus user's
# ~/.local/bin because we are already USER cyrrus.
USER cyrrus
ENV UV_VERSION=0.13.8
RUN curl -fLsSf "https://astral.sh/uv/install.sh" | sh

# Install the cyrrus tool (re-installed so the runtime image only carries what's needed).
ENV PATH="/home/cyrrus/.local/bin:$PATH"
RUN uv tool install --prerelease allow cyrrus

# Working directory and data directory.
WORKDIR /home/cyrrus
ENV DATA_DIR=/data
# The /data directory is intended to be mounted at runtime via:
#   docker run -v cyrrus-data:/data ...
# The VOLUME directive below marks it for that purpose.  We do not mkdir during
# build because the cyrrus user does not have permission to create directories
# in the root-owned image filesystem; instead, the host provides the volume.
VOLUME ["$DATA_DIR"]

# Entrypoint: cyrrus with a config path.
# The config file may set api_key_env; if it does, non-loopback binding is
# allowed (Bearer token auth).  If api_key_env is unset or empty, the gateway
# binds to 127.0.0.1 only — no network exposure in the default configuration.
# The CLI expects the subcommand (e.g. "serve") as the first positional argument.
ENTRYPOINT ["cyrrus"]
CMD ["serve", "--config", "/data/config.json"]

# ---------- Buildx multi-arch workflow snippet (GitHub Actions) ----------
# The following snippet is for .github/workflows/docker.yml; it is NOT part of
# the Dockerfile itself but shown for completeness.
#
# api-key-env note:
#   Set CYRRUS_AUTH_TOKEN_ENV in the config to require a bearer token on
#   incoming requests.  The gateway uses a constant-time compare (never logs
#   the token).  If unset, the gateway binds to 127.0.0.1 only — this image
#   defaults to that safe configuration.