#!/usr/bin/env bash
set -euo pipefail

VERSION="${1:-latest}"
INSTALL_DIR="${2:-$HOME/.local/bin}"

if [ -x "$(command -v gh 2>/dev/null)" ]; then
  echo "gh 已安裝：$(gh --version | head -n 1)"
  gh --version
else
  echo "未偵測到 gh，開始下載安裝..."
  mkdir -p "$INSTALL_DIR"

  OS="$(uname -s)"
  case "$OS" in
    Darwin)
      TAR_NAME="gh_${VERSION}_macOS_arm64.tar.gz"
      ;;
    *)
      echo "目前腳本預設只支援 macOS；其他平台請手動安裝"
      exit 1
      ;;
  esac

  case "$VERSION" in
    latest)
      URL="https://github.com/cli/cli/releases/latest/download/gh_2.79.0_macOS_arm64.tar.gz"
      ;;
    *)
      VERSION_TAG="$VERSION"
      case "$VERSION_TAG" in
        v*) ;;
        *) VERSION_TAG="v$VERSION_TAG" ;;
      esac
      URL="https://github.com/cli/cli/releases/download/$VERSION_TAG/$TAR_NAME"
      ;;
  esac
  TMP_DIR="$(mktemp -d)"
  trap 'rm -rf "$TMP_DIR"' EXIT

  echo "下載: $URL"
  curl -fL "$URL" -o "$TMP_DIR/gh.tar.gz"
  tar -xzf "$TMP_DIR/gh.tar.gz" -C "$TMP_DIR"
  GHDIR="$(find "$TMP_DIR" -maxdepth 2 -type d -name 'gh_*' | head -n 1)"
  if [ -z "$GHDIR" ]; then
    echo "找不到解壓後的 gh 目錄"
    exit 1
  fi
  install -m 0755 "$GHDIR/bin/gh" "$INSTALL_DIR/gh"
  echo "已安裝到 $INSTALL_DIR/gh"

  if ! echo ":$PATH:" | grep -q ":$INSTALL_DIR:"; then
    echo "提醒：請先把 $INSTALL_DIR 加入 PATH。"
    echo "在 ~/.zshrc 內加："
    echo "export PATH=\"$INSTALL_DIR:\$PATH\""
  fi
fi

"$INSTALL_DIR/gh" --version
"$INSTALL_DIR/gh" auth status || true
