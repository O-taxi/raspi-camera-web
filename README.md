# raspi-camera-web

Raspberry Piに接続したカメラを、Tailscale内のブラウザーから操作するための小さなWebアプリです。

## 機能

- ブラウザーから写真を撮影
- 撮影結果をその場で表示
- 撮影した写真を8枚ずつ一覧表示
- 履歴写真の拡大表示と削除
- 保存枚数による自動整理
- 実カメラなしで試せるモック撮影
- Raspberry Piカメラモジュールでは、ライブ映像と動体検知による動画保存を利用可能

一般インターネットには公開せず、Tailscaleに参加している端末からだけ利用する構成を前提とします。

## 技術スタック

- Raspberry Pi 3B / Raspberry Pi OS（Python 3.9以上）
- USBカメラ（`fswebcam`）または Raspberry Pi カメラモジュール（`rpicam-still` / `Picamera2`）
- Python 3 / FastAPI / Uvicorn
- Jinja2 / HTML / CSS / Vanilla JavaScript
- systemd
- Tailscale Serve

## 通信シーケンス

```mermaid
sequenceDiagram
    actor User as ブラウザー
    participant Tailscale as Tailscale Serve
    participant API as FastAPI<br/>127.0.0.1:8000
    participant Camera as CameraService
    participant Command as fswebcam / rpicam-still
    participant Hardware as USBカメラ / CSIカメラ
    participant Store as data/photos

    User->>Tailscale: HTTPS POST /api/capture
    Tailscale->>API: HTTP POST /api/capture
    API->>Camera: 撮影要求
    Camera->>Command: 出力先を指定して実行
    Command->>Hardware: フレーム取得
    Hardware-->>Command: カメラ画像
    Command->>Store: JPEGを保存
    Command-->>Camera: 終了結果
    Camera->>Store: 出力確認・保存上限の整理
    Camera-->>API: 写真ID・撮影時刻・URL
    API-->>Tailscale: JSON
    Tailscale-->>User: 撮影結果

    User->>Tailscale: HTTPS GET /api/photos
    Tailscale->>API: HTTP GET /api/photos
    API->>Store: 写真一覧を取得
    Store-->>API: 写真メタデータ
    API-->>Tailscale: JSON
    Tailscale-->>User: 写真一覧

    User->>Tailscale: HTTPS GET /photos/{photo_id}
    Tailscale->>API: HTTP GET /photos/{photo_id}
    API->>Store: IDを検証してJPEGを取得
    Store-->>API: JPEG
    API-->>Tailscale: JPEG
    Tailscale-->>User: 画像

    User->>Tailscale: HTTPS DELETE /api/photos/{photo_id}
    Tailscale->>API: HTTP DELETE /api/photos/{photo_id}
    API->>Store: IDを検証して削除
    API-->>Tailscale: 204 No Content
    Tailscale-->>User: 削除完了
```

同一端末から`127.0.0.1:8000`へ直接接続する場合は、Tailscale Serveを経由しません。

## カメラを接続して起動

次のいずれか一方だけを選びます。USBカメラとCSIカメラでは、診断・起動設定が異なります。

### 共通の準備

Raspberry Pi OS上で、リポジトリをcloneした通常のログインユーザーで実行します。スクリプトがカメラ用APTパッケージ、uv、ロック済みPython依存を導入します。

```bash
./scripts/install_raspberry_pi_dependencies.sh
```

### USBカメラを使う場合（`fswebcam`）

USBカメラを接続し、撮影可能なV4L2デバイスとして認識されていることを確認します。ここで使うデバイスは既定で`/dev/video0`です。

```bash
uv run --no-sync python scripts/check_usb_camera.py --device /dev/video0
```

`OK: 撮影可能なUSBカメラを1台認識しています。`と表示されたら、アプリと同じ条件でテスト撮影します。

```bash
fswebcam \
  --device /dev/video0 \
  --resolution 1280x720 \
  --no-banner \
  /tmp/raspi-camera-test.jpg
file /tmp/raspi-camera-test.jpg
```

JPEGとして保存できたら、USBバックエンドで起動します。

```bash
# USBカメラ
CAMERA_BACKEND=fswebcam CAMERA_DEVICE=/dev/video0 \
uv run --no-sync uvicorn app.main:app \
  --host 127.0.0.1 \
  --port 8000
```

### CSIカメラを使う場合（リボンケーブル接続）

`/dev/video0`や`CAMERA_DEVICE`は使用しません。最初にCSIカメラの認識とテスト撮影を確認します。

```bash
uv run --no-sync python scripts/check_csi_camera.py --capture
```

静止画のみなら、`rpicam-still`を使うバックエンドで起動します。

```bash
CAMERA_BACKEND=rpicam \
CAMERA_COMMAND=rpicam-still \
uv run --no-sync uvicorn app.main:app \
  --host 127.0.0.1 \
  --port 8000
```

ライブ映像または動体検知録画も使う場合は、単発撮影用の`rpicam`ではなくPicamera2を選びます。

```bash
PYTHONPATH=/usr/lib/python3/dist-packages \
CAMERA_BACKEND=picamera2 \
uv run --no-sync uvicorn app.main:app \
  --host 127.0.0.1 \
  --port 8000
```

Picamera2の詳細設定は[動画・動体検知の運用](docs/video-and-motion.md)を参照してください。

同じ端末では`http://127.0.0.1:8000`を開きます。Tailscale内の別端末から接続する場合は、先にTailscale Serveを設定してHTTPSのURLを開きます。

常用時はUvicornをsystemdで常駐させ、Tailscale Serveから`127.0.0.1:8000`へ転送します。Tailscaleの設定は [docs/tailscale-setup.md](docs/tailscale-setup.md) を参照してください。

開発手順と現在の実装状況は [docs/development.md](docs/development.md) を参照してください。

## 想定API

```text
POST   /api/capture             写真を撮影する
GET    /api/photos              保存済み写真の一覧を取得する
GET    /photos/{photo_id}       写真を取得する
DELETE /api/photos/{photo_id}  写真を削除する
GET    /stream.mjpg             Picamera2のライブ映像を取得する
GET    /api/videos              動体検知で保存した動画の一覧を取得する
GET    /videos/{video_id}       保存した動画を取得する
```

USBカメラの詳細、旧 Raspberry Pi OSの`libcamera-still`、systemd設定は[Raspberry Piとカメラのセットアップ](docs/raspberry-pi-setup.md)を参照してください。

## セキュリティ方針

- アプリは `127.0.0.1` のみで待ち受ける
- Tailscale Funnelは使用しない
- ルーターでHTTP、HTTPS、SSHのポートを開放しない
- 撮影操作には `POST` を使い、同時撮影と連打を制限する
- 撮影画像、秘密情報、端末固有設定はGitへ登録しない

## 開発者向け情報

実装方針と検証ルールは [AGENTS.md](AGENTS.md) に記載しています。
