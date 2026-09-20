# 開発ガイドと実装状況

## 開発環境

- WSL Ubuntu 26.04
- uv
- uv管理のPython
- 実カメラなしでも動作確認できるモック撮影モード

Python、仮想環境、依存関係はuvへ統一します。`pip`を直接使用せず、`requirements.txt`との二重管理も行いません。

想定する初期セットアップ：

```bash
uv python install 3.13
uv python pin 3.13
uv sync
```

開発サーバー：

```bash
CAMERA_BACKEND=mock uv run uvicorn app.main:app \
  --host 127.0.0.1 \
  --port 8000 \
  --reload
```

ブラウザーで `http://127.0.0.1:8000` を開きます。

検証：

```bash
uv run ruff check .
uv run pytest
```

## 実装済み

- FastAPIアプリケーションとJinja2テンプレート
- レスポンシブな撮影画面
- `POST /api/capture`
- `GET /api/photos`
- `GET /photos/{photo_id}`
- `DELETE /api/photos/{photo_id}`
- 撮影履歴の拡大表示、削除、8枚単位のページング
- `fswebcam`を使うUSBカメラ撮影サービス
- `/dev/video0`、解像度、タイムアウトなどの環境変数設定
- 同時撮影拒否
- 最小撮影間隔による連打制限
- 撮影タイムアウトとコマンド失敗の処理
- 最大保存枚数を超えた古い写真の削除
- 写真ID検証とパストラバーサル対策
- クロスサイトブラウザー要求の拒否
- systemd unit
- カメラサービス、ファイル管理、HTTPルートのテストコード
- Raspberry Pi、USBカメラ、Tailscaleのセットアップ文書

## uv移行とモック撮影の実装状況

次の作業は完了している。

- 実行時依存関係と`dev` dependency groupの`pyproject.toml`への移行
- 一時的な`requirements.txt`と`requirements-dev.txt`の削除
- `.python-version`によるPython 3.13の指定
- `uv.lock`の生成
- `CAMERA_BACKEND=mock`と有効なJPEGを保存するモック撮影の実装
- バックエンド設定とモック撮影の自動テスト

Python 3.13のローカル環境では、次を確認済み。

- `uv sync`が成功する。
- `uv run ruff check .`が成功する。
- `uv run pytest`が成功する。
- Uvicornを起動し、HTTP経由で撮影、JPEG取得、履歴更新が成功する。

ブラウザー上の表示と操作感は、WSL上で別途目視確認する。

## カメラバックエンドの方針

`CAMERA_BACKEND`は次の値だけを受け付ける。

```text
fswebcam  Raspberry Pi上のUSBカメラ。既定値
mock      WSLやCI向け。外部カメラを使わない
```

未知の値は起動時に設定エラーとする。HTTPリクエストからバックエンドやコマンドを指定できるようにはしない。

モックも実カメラと同じ`CameraService`の排他制御、タイムアウト、保存上限を通す。これにより、WSL上でも画面から撮影APIまでの一連の流れを確認できるようにする。

## 実機との差分

WSLのモック確認で保証できるのは、Web画面、API、ファイル保存、エラー処理までです。以下はRaspberry Pi上で別途確認する。

- USBカメラのVideo4Linux2認識
- `fswebcam`による実撮影
- `video`グループの権限
- systemdの自動起動と再起動
- Tailscale Serve経由のHTTPS接続
- Pi 3Bでのメモリ使用量と撮影時間
