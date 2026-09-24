# raspi-camera-web

Raspberry Pi 3Bに接続したカメラを、Tailscale内のブラウザーから操作するWebアプリです。FastAPI、Jinja2、Vanilla JavaScriptで動作し、本番環境ではsystemdとTailscale Serveを使います。

## 主な機能

- USBカメラまたはCSIカメラでの写真撮影、履歴の表示・削除
- CSIカメラとPicamera2によるライブ映像、動体検知録画
- 写真・動画の保存上限と、カメラなしで試せるモック撮影

## 開発環境で試す

```bash
uv sync
CAMERA_BACKEND=mock uv run uvicorn app.main:app --host 127.0.0.1 --port 8000
```

`http://127.0.0.1:8000/`を開きます。モックはカメラを使用せず、テスト用JPEGを保存します。

実機への導入は[セットアップ手順](docs/raspberry-pi-setup.md)、Tailscaleの設定は[Tailscale Serve設定](docs/tailscale-setup.md)を参照してください。バックエンド・API・設定値は[仕様](docs/specification.md)、開発と実機確認の状況は[開発ガイド](docs/development.md)にまとめています。
