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
MOTION_MIN_CHANGED_RATIO=0.003 \
MOTION_ILLUMINATION_CHANGED_RATIO=0.65 \
MOTION_ILLUMINATION_DIRECTION_RATIO=0.90 \
MOTION_SETTLE_SECONDS=5 \
MOTION_MINIMUM_CONSECUTIVE_FRAMES=3 \
MOTION_RECORD_SECONDS=20 \
MOTION_MAX_RECORD_SECONDS=60 \
MOTION_ENABLED=true \
uv run --no-sync uvicorn app.main:app --host 127.0.0.1 --port 8000
```

`/stream.mjpg`をブラウザーで開くとカラーのライブ映像を確認できます。Picamera2の互換性のため、カメラからの低解像度ストリームはYUV420で取得し、輝度は動体検知へ、色差成分はブラウザー向けカラーMJPEGへ使います。録画終了時もライブ配信を止めず、録画用H.264エンコーダーだけを停止します。

録画終了後、アプリ画面下部の「録画動画」に保存済みMP4が新しい順に表示されます。動画一覧は約10秒ごとに更新されます。「ダウンロード」を押すと、動画ファイルを端末へ保存できます。動画ファイルは既定で`data/videos/`に保存され、`GET /api/videos`で一覧、`GET /videos/{video_id}`でダウンロードできます。

## 動体検知の遠隔操作と録画上限

Picamera2モードの画面には動体検知のON/OFF操作があります。OFFにすると、ライブ映像は継続したまま、新しい動体検知録画を開始しません。録画中にOFFへ切り替えた場合は、その録画を終了します。状態は`VIDEO_DIR`内の`.motion-state.json`へ保存するため、サービス再起動後も維持されます。

APIを使う場合は、現在の状態を`GET /api/motion`で取得し、次のように`PUT /api/motion`で切り替えられます。

```bash
curl --request PUT http://127.0.0.1:8000/api/motion \
  --header 'Content-Type: application/json' \
  --data '{"enabled": false}'
```

`MOTION_MAX_RECORD_SECONDS`は、動きが継続しても1本の動画を必ず終了する絶対上限です。`MOTION_RECORD_SECONDS`（最後に動きを検知してから録画を続ける秒数）以上に設定してください。既定値は60秒です。録画終了後は既存の`MOTION_COOLDOWN_SECONDS`の間、新たな録画を開始しません。

ケージ内の小さく短い動きを記録したい場合は、最初は`MOTION_MINIMUM_CONSECUTIVE_FRAMES=2`に下げ、`MOTION_THRESHOLD`を少しずつ下げながら実機映像で調整してください。ケージ外の動きや照明変化による誤検知が多い場合は、次段階として検知エリア指定を追加します。

## 照明変化の除外

動体検知は、間引いた輝度画素ごとの差を調べます。`MOTION_THRESHOLD`以上に変化した画素の割合が`MOTION_MIN_CHANGED_RATIO`以上なら、通常の動きの候補です。この方式により、小さな領域だけが動く場合も調整できます。

一方で、`MOTION_ILLUMINATION_CHANGED_RATIO`以上の画素が変化し、そのうち`MOTION_ILLUMINATION_DIRECTION_RATIO`以上が同時に明るくなる、または暗くなる場合は、照明ON/OFF・カーテン・自動露出などによる全体的な明るさ変化として除外します。検出後は`MOTION_SETTLE_SECONDS`の間、新規録画を開始せず、直後の露出調整による連続誤検知を防ぎます。

既定値は、全体の65%以上が同方向へ変化した場合に照明変化と判断し、5秒間待機します。ケージ内のヤモリ向けには、まず`MOTION_MIN_CHANGED_RATIO=0.003`、`MOTION_MINIMUM_CONSECUTIVE_FRAMES=2`で試し、照明変化が残る場合は`MOTION_ILLUMINATION_CHANGED_RATIO`を下げてください。画角にケージ外が大きく入る場合の検知エリア指定は、別の機能として追加できます。

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
