#!/usr/bin/env sh
# Cyrrus installer for macOS, Linux and Raspberry Pi (64-bit).
#
# Usage:
#   sh install.sh                          # install from PyPI with uv
#   sh install.sh 0.3.0                    # pin an exact PyPI version
#   sh install.sh --binary --version 0.3.0
#
# A stable release needs no extra flags.  To install a pre-release that is not
# selected by default, opt in explicitly:
#   CYRRUS_PRERELEASE=1 sh install.sh
#
# The default mode uses uv, which installs console tools into their own
# environment and keeps them off the system Python.  `--binary` skips Python
# and downloads the standalone release archive instead.  Neither mode needs
# root.
#
# Termux and 32-bit systems (for example 32-bit Raspberry Pi OS) are not
# supported by uv or by the released binaries; use pip instead.

set -eu

VERSION="${CYRRUS_VERSION:-}"
BINARY=0

say() {
    printf '%s\n' "$*"
}

fail() {
    printf 'ERROR: %s\n' "$*" >&2
    exit 1
}

usage() {
    cat <<'EOF'
Usage: install.sh [VERSION] [--binary] [--version VERSION]

  VERSION / --version VERSION   install an exact version
  --binary                      download the standalone archive (explicit
                                version required); no Python or uv needed
EOF
}

download() {
    url="$1"
    out="$2"
    if command -v curl >/dev/null 2>&1; then
        # curl does not set the macOS quarantine flag that a browser download
        # does.  GitHub serves over HTTPS and the archive is verified below.
        curl -fLsS "$url" -o "$out" || fail "download failed: $url"
    elif command -v wget >/dev/null 2>&1; then
        wget -q "$url" -O "$out" || fail "download failed: $url"
    else
        fail "curl or wget is required to download a release archive."
    fi
}

while [ "$#" -gt 0 ]; do
    case "$1" in
        --binary)
            BINARY=1
            shift
            ;;
        --version)
            [ "$#" -ge 2 ] || fail "--version needs a value."
            VERSION="$2"
            shift 2
            ;;
        --version=*)
            VERSION="${1#*=}"
            shift
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        --*)
            fail "unknown option '$1'. Run with --help for usage."
            ;;
        *)
            [ -z "$VERSION" ] || fail "version given twice ('$VERSION' and '$1')."
            VERSION="$1"
            shift
            ;;
    esac
done

# uv does not support Termux (it has no Android wheels), so be explicit
# instead of failing later inside uv.
if [ -n "${TERMUX_VERSION:-}" ] || [ -d /data/data/com.termux ]; then
    fail "Termux is not supported by this installer: uv does not support Termux.
Install with pip instead:
  pkg install python
  pip install cyrrus"
fi

OS_NAME="$(uname -s 2>/dev/null || echo unknown)"
case "$OS_NAME" in
    Darwin) os=macos ;;
    Linux) os=linux ;;
    *)
        fail "unsupported operating system '$OS_NAME'. Install with pip instead:
  python3 -m pip install cyrrus"
        ;;
esac

MACHINE="$(uname -m 2>/dev/null || echo unknown)"
case "$MACHINE" in
    x86_64|amd64) arch=x64 ;;
    arm64|aarch64) arch=arm64 ;;
    *)
        fail "unsupported architecture '$MACHINE' (32-bit systems such as 32-bit Raspberry Pi OS have no binary). Install with pip instead:
  python3 -m pip install cyrrus"
        ;;
esac

if [ "$BINARY" = "1" ]; then
    [ -n "$VERSION" ] || fail "binary mode needs an explicit version (--version X or CYRRUS_VERSION)."
    VERSION="${VERSION#v}"
    ASSET="cyrrus-${VERSION}-${os}-${arch}.tar.gz"

    if [ -n "${CYRRUS_RELEASE_BASE_URL:-}" ]; then
        # Test hook: point the installer at a local fake release.
        BASE="${CYRRUS_RELEASE_BASE_URL%/}"
    else
        BASE="https://github.com/kikusuka/cyrrus/releases/download/v${VERSION}"
    fi

    TMP="$(mktemp -d)"
    trap 'rm -rf "$TMP"' EXIT HUP INT TERM
    say "Downloading $BASE/$ASSET ..."
    download "$BASE/SHA256SUMS" "$TMP/SHA256SUMS"
    download "$BASE/$ASSET" "$TMP/$ASSET"

    EXPECTED="$(awk -v name="$ASSET" '$2 == name { print $1 }' "$TMP/SHA256SUMS" | head -n 1)"
    [ -n "$EXPECTED" ] || fail "SHA256SUMS does not list $ASSET."

    if command -v sha256sum >/dev/null 2>&1; then
        ACTUAL="$(sha256sum "$TMP/$ASSET" | awk '{ print $1 }')"
    elif command -v shasum >/dev/null 2>&1; then
        ACTUAL="$(shasum -a 256 "$TMP/$ASSET" | awk '{ print $1 }')"
    else
        fail "sha256sum or shasum is required to verify the download."
    fi
    [ "$ACTUAL" = "$EXPECTED" ] || fail "checksum mismatch for $ASSET. Expected $EXPECTED but got $ACTUAL. Do not run this file."
    say "SHA-256 verified: $ACTUAL"

    DEST="$HOME/.local/bin/cyrrus"
    mkdir -p "$HOME/.local/bin"
    rm -rf "$DEST"
    mkdir -p "$DEST"
    tar -xzf "$TMP/$ASSET" -C "$DEST"
    [ -f "$DEST/cyrrus" ] || fail "the archive did not contain the cyrrus executable."
    # The tarball preserves the executable bit; chmod is belt and braces for
    # tools that lose it while extracting.
    chmod +x "$DEST/cyrrus"

    say ""
    say "Cyrrus is installed at $DEST/cyrrus"
    say ""
    say "Add this folder to your PATH:"
    say "  export PATH=\"$DEST:\$PATH\""
    say "Then open a NEW terminal and run: cyrrus --version"
    say ""
    say "Uninstall later by deleting: $DEST"
    exit 0
fi

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

# Stable releases install with no special flags.  Pre-releases are opt-in.
install_tool() {
    if [ "${CYRRUS_PRERELEASE:-}" = "1" ]; then
        uv tool install --prerelease allow "$@"
    else
        uv tool install "$@"
    fi
}

if [ -n "$VERSION" ]; then
    VERSION="${VERSION#v}"
    say "Installing cyrrus $VERSION with uv..."
    install_tool "cyrrus==$VERSION" \
        || fail "uv tool install failed. Check your network connection and the version number."
else
    say "Installing cyrrus with uv..."
    install_tool cyrrus \
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
