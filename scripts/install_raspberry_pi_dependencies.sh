#!/usr/bin/env bash
# Raspberry Pi OS上でraspi-camera-webの依存関係を導入する。
#
# 使い方:
#   ./scripts/install_raspberry_pi_dependencies.sh
#
# 引数:
#   このスクリプトは引数を受け付けない。リポジトリをcloneした通常の
#   ログインユーザーで実行する。APT操作だけにsudoを使用する。

set -euo pipefail

if [[ "$#" -ne 0 ]]; then
  echo "使い方: ./scripts/install_raspberry_pi_dependencies.sh" >&2
  exit 2
fi

project_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
target_user="$(id -un)"

if [[ "${EUID}" -eq 0 ]]; then
  echo "sudoを付けず、通常のログインユーザーで実行してください。" >&2
  echo "このスクリプトは必要なAPT操作だけにsudoを使用します。" >&2
  exit 1
fi

if ! command -v apt-get >/dev/null 2>&1; then
  echo "このスクリプトはAPTを使うRaspberry Pi OS向けです。" >&2
  exit 1
fi

if ! command -v sudo >/dev/null 2>&1; then
  echo "sudoが見つかりません。APTパッケージを導入できません。" >&2
  exit 1
fi

sudo apt-get update

if apt-cache show rpicam-apps >/dev/null 2>&1; then
  camera_apps_package="rpicam-apps"
elif apt-cache show libcamera-apps >/dev/null 2>&1; then
  camera_apps_package="libcamera-apps"
else
  echo "rpicam-appsまたはlibcamera-appsがAPTリポジトリに見つかりません。" >&2
  exit 1
fi

sudo apt-get install --yes --no-install-recommends \
  ca-certificates \
  curl \
  ffmpeg \
  fswebcam \
  git \
  python3 \
  python3-picamera2 \
  python3-venv \
  v4l-utils \
  "${camera_apps_package}"

if ! command -v uv >/dev/null 2>&1; then
  curl -LsSf https://astral.sh/uv/install.sh | env UV_INSTALL_DIR="${HOME}/.local/bin" sh
  export PATH="${HOME}/.local/bin:${PATH}"
fi

sudo usermod -aG video "${target_user}"

cd "${project_dir}"
uv sync --python /usr/bin/python3 --no-python-downloads --no-dev --locked

PYTHONPATH=/usr/lib/python3/dist-packages \
  uv run --no-sync python -c 'from picamera2 import Picamera2; print("Picamera2 import: OK")'

echo "raspi-camera-webの依存関係を導入しました。"
echo "USBカメラを使う場合は、ログアウトして再ログイン後にvideoグループが有効になります。"
echo "CSIカメラは rpicam-hello --list-cameras で認識を確認してください。"
echo "Tailscaleの導入と認証は docs/tailscale-setup.md の手順で別途行ってください。"
