#!/usr/bin/env sh
# Cyrrus installer for macOS, Linux, Raspberry Pi and Termux.
#
# Usage:
#   sh install.sh              # install the latest release (pre-releases allowed)
#   sh install.sh 0.3.0b6      # pin an exact version
#
# uv is used because it installs console tools into their own environment and
# keeps them off the system Python. No root or admin rights are required.

set -eu

VERSION="${1:-}"

say() {
    printf '%s\n' "$*"
}

fail() {
    printf 'ERROR: %s\n' "$*" >&2
    exit 1
}

# Official uv standalone installer:
# https://docs.astral.sh/uv/getting-started/installation/#standalone-installer
# (macOS/Linux: curl -LsSf https://astral.sh/uv/install.sh | sh)
if ! command -v uv >/dev/null 2>&1; then
    say "uv not found. Installing uv with the official installer..."
    if command -v curl >/dev/null 2>&1; then
        curl -LsSf https://astral.sh/uv/install.sh | sh || fail "uv installation failed (curl)."
    elif command -v wget >/dev/null 2>&1; then
        wget -qO- https://astral.sh/uv/install.sh | sh || fail "uv installation failed (wget)."
    else
        fail "curl or wget is required to install uv. Install one and re-run this script."
    fi
    # uv's installer puts binaries in ~/.local/bin but only updates future
    # shells. Use it for the rest of this script without changing anything
    # permanently.
    PATH="$HOME/.local/bin:$PATH"
    export PATH
fi

command -v uv >/dev/null 2>&1 || fail "uv is still not available. Open a new terminal and re-run this script."

if [ -n "$VERSION" ]; then
    say "Installing cyrrus $VERSION with uv..."
    uv tool install --prerelease allow "cyrrus==$VERSION" \
        || fail "uv tool install failed. Check your network connection and the version number."
else
    say "Installing cyrrus with uv..."
    # TODO: remove --prerelease once a stable release exists on PyPI.
    uv tool install --prerelease allow cyrrus \
        || fail "uv tool install failed. Check your network connection."
fi

# Add uv's tool directory to the shell profile so future shells find cyrrus.
uv tool update-shell || fail "uv tool update-shell failed."

say ""
say "Cyrrus is installed."
say ""
say "Open a NEW terminal and run: cyrrus setup"
say ""
say "Uninstall later with: uv tool uninstall cyrrus"
