---
title: ライブ映像と動体検知録画
description: Picamera2によるライブ映像と動体検知動画保存の設定
---

# ライブ映像と動体検知録画

## 対象と制約

この機能は、リボンケーブルで接続したRaspberry Piカメラモジュールを対象とします。USBカメラの`fswebcam`バックエンドでは利用できません。カメラはPicamera2サービスが常時1つだけ所有するため、`rpicam-still`などの別プロセスを並行して起動しないでください。

Pi 3BではCPUとメモリに余裕がないため、ライブ表示・動体検知・H.264エンコードを低負荷な設定から始めます。ブラウザーへは互換性を優先したMJPEGを配信し、保存動画はH.264をMP4コンテナへ出力します。

## Raspberry Pi OSの準備

Raspberry Pi OSでPicamera2とFFmpegを導入します。Picamera2はlibcameraとの組み合わせが必要なため、Pythonパッケージ管理ではなくOSパッケージを使用します。

```bash
./scripts/install_raspberry_pi_dependencies.sh
```

このスクリプトはカメラ関連パッケージに加え、uvとこのプロジェクトのロック済みPython依存関係まで導入します。APT操作だけでsudoを使うため、通常のログインユーザーで実行してください。

アプリを起動するユーザーと同じ条件で、Picamera2を読み込めることを確認します。Picamera2はRaspberry Pi OSの`/usr/lib/python3/dist-packages`に入るため、uvで作る仮想環境からはこのパスを明示します。アプリの仮想環境はOSのPythonを基に作成してください。

```bash
uv sync --python /usr/bin/python3 --no-python-downloads --no-dev --locked
PYTHONPATH=/usr/lib/python3/dist-packages \
uv run --no-sync python -c 'from picamera2 import Picamera2; print(Picamera2.global_camera_info())'
```

## 起動設定

`CAMERA_BACKEND=picamera2`を指定します。以下はPi 3B向けの初期設定です。検知感度は設置後の映像を確認して調整してください。

```bash
PYTHONPATH=/usr/lib/python3/dist-packages \
CAMERA_BACKEND=picamera2 \
LIVE_STREAM_WIDTH=640 \
LIVE_STREAM_HEIGHT=360 \
LIVE_STREAM_FPS=5 \
MOTION_THRESHOLD=12 \
MOTION_MINIMUM_CONSECUTIVE_FRAMES=3 \
MOTION_RECORD_SECONDS=20 \
uv run --no-sync uvicorn app.main:app --host 127.0.0.1 --port 8000
```

`/stream.mjpg`をブラウザーで開くとライブ映像を確認できます。動体検知では、ライブ用フレームの輝度を間引いて画素差分を計算します。動画ファイルは既定で`data/videos/`に保存され、`GET /api/videos`で一覧、`GET /videos/{video_id}`で取得できます。

## systemd設定

```bash
uv run python scripts/configure_systemd.py \
  --camera-backend picamera2 \
  --enable-now
```

動画の保存先は写真とは分離し、サービス実行ユーザーだけが書き込めるようにします。設定スクリプトは動画用の環境変数と、Picamera2用の`PYTHONPATH`を生成します。

## 動作確認

1. `uv run --no-sync python scripts/check_csi_camera.py --capture`でカメラ認識とJPEG撮影を確認する。
2. アプリ起動後に`/stream.mjpg`を開き、映像とCPU使用量を確認する。
3. カメラ前で動き、`data/videos/`にMP4が作成されること、ブラウザーで再生できることを確認する。
4. 誤検知、検知後の録画長、保存上限、数時間の連続稼働を確認する。
5. `sudo systemctl restart raspi-camera-web.service`後に映像と録画が復旧することを確認する。

実機確認の前に、解像度やフレームレートを上げないでください。OpenCVによる解析や人物検出を追加する場合は、別途Pi 3Bでの負荷測定を行います。
