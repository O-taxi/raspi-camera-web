---
title: ライブ映像と動体検知録画
description: Picamera2によるライブ映像と動体検知動画保存の設定
---

# ライブ映像と動体検知録画

## 目次

- [対象と制約](#対象と制約)
- [Raspberry Pi OSの準備](#raspberry-pi-osの準備)
- [起動設定](#起動設定)
- [動体検知の遠隔操作と録画上限](#動体検知の遠隔操作と録画上限)
- [照明変化の除外](#照明変化の除外)
- [周期的に録画される場合の確認](#周期的に録画される場合の確認)
- [systemd設定](#systemd設定)
- [動作確認](#動作確認)

## 対象と制約

この機能は、リボンケーブルで接続したRaspberry Piカメラモジュールを対象とします。USBカメラの`fswebcam`バックエンドでは利用できません。カメラはPicamera2サービスが常時1つだけ所有するため、`rpicam-still`などの別プロセスを並行して起動しないでください。

Pi 3BではCPUとメモリに余裕がないため、ライブ表示・動体検知・H.264エンコードを低負荷な設定から始めます。ブラウザーへは互換性を優先したMJPEGを配信し、保存動画はH.264をMP4コンテナへ出力します。

## Raspberry Pi OSの準備

Raspberry Pi OSでPicamera2とFFmpegを導入します。Picamera2はlibcameraとの組み合わせが必要なため、Pythonパッケージ管理ではなくOSパッケージを使用します。

```bash
./scripts/install_raspberry_pi_dependencies.sh
```

このスクリプトはカメラ関連パッケージに加え、uvとこのプロジェクトのロック済みPython依存関係まで導入します。APT操作だけでsudoを使うため、通常のログインユーザーで実行してください。Pi上のPythonコマンドは既存環境を使う`uv run --no-sync`で実行します。

アプリを起動するユーザーと同じ条件で、Picamera2を読み込めることを確認します。Picamera2はRaspberry Pi OSの`/usr/lib/python3/dist-packages`に入るため、uvで作る仮想環境からはこのパスを明示します。アプリの仮想環境はOSのPythonを基に作成してください。

```bash
uv sync --python /usr/bin/python3 --no-python-downloads --no-dev --locked
PYTHONPATH=/usr/lib/python3/dist-packages \
uv run --no-sync python -c 'from picamera2 import Picamera2; print(Picamera2.global_camera_info())'
```

アプリまたはsystemdサービスを起動する前に、`uv run --no-sync python scripts/check_csi_camera.py --capture`でカメラ認識とJPEG撮影を確認します。Picamera2の稼働中には別プロセスのカメラ診断を実行しません。

## 起動設定

`CAMERA_BACKEND=picamera2`を指定します。以下はPi 3B向けの初期設定です。検知感度は設置後の映像を確認して調整してください。

```bash
PYTHONPATH=/usr/lib/python3/dist-packages \
CAMERA_BACKEND=picamera2 \
LIVE_STREAM_WIDTH=640 \
LIVE_STREAM_HEIGHT=360 \
LIVE_STREAM_FPS=5 \
MOTION_THRESHOLD=12 \
MOTION_ANALYSIS_TILE_SIZE=32 \
MOTION_MIN_CHANGED_RATIO=0.10 \
MOTION_ILLUMINATION_CHANGED_RATIO=0.65 \
MOTION_ILLUMINATION_DIRECTION_RATIO=0.90 \
MOTION_SETTLE_SECONDS=5 \
MOTION_MINIMUM_CONSECUTIVE_FRAMES=3 \
MOTION_RECORD_SECONDS=20 \
MOTION_MIN_RECORD_SECONDS=2 \
MOTION_MAX_RECORD_SECONDS=60 \
MOTION_ENABLED=true \
uv run --no-sync uvicorn app.main:app --host 127.0.0.1 --port 8000
```

`/stream.mjpg`をブラウザーで開くとカラーのライブ映像を確認できます。Picamera2の互換性のため、カメラからの低解像度ストリームはYUV420で取得し、輝度は動体検知へ、色差成分はブラウザー向けカラーMJPEGへ使います。録画終了時もライブ配信を止めず、録画用H.264エンコーダーだけを停止します。

録画終了後、アプリ画面下部の「録画動画」に保存済みMP4が新しい順に表形式で表示されます。動画一覧は約10秒ごとに更新され、10件を超えるとページを切り替えられます。新規に録画した動画には時間も表示されます。「ダウンロード」アイコンを押すと、動画ファイルを端末へ保存できます。ゴミ箱アイコンでは確認後に動画を削除し、対応する再生時間メタデータも同時に削除します。動画ファイルは既定で`data/videos/`に保存され、`GET /api/videos`で一覧、`GET /videos/{video_id}`でダウンロード、`DELETE /api/videos/{video_id}`で削除できます。

## 動体検知の遠隔操作と録画上限

Picamera2モードの画面には動体検知の開始・停止操作があります。確認ダイアログで停止を確定すると、ライブ映像は継続したまま新しい動体検知を止め、進行中の一時録画も保存せず破棄します。状態は`VIDEO_DIR`内の`.motion-state.json`へ保存するため、サービス再起動後も維持されます。保存状態は`MOTION_ENABLED`より優先され、状態ファイルがない場合は環境変数を初期値にします。不正または読み取り不能な状態ファイルがある場合はOFFで起動します。

アプリへ接続できる全員が写真を撮影・削除し、動画を削除し、動体検知設定を変更できます。共有相手と端末はTailscaleのアクセス制御で絞ってください。

APIを使う場合は、現在の状態を`GET /api/motion`で取得し、次のように`PUT /api/motion`で切り替えられます。応答には`enabled`に加えて`state`（`disabled`、`waiting`、`recording`、`cooldown`、`error`）、`stream_state`（`starting`、`streaming`、`stale`）、`last_frame_at`（UTC ISO 8601または`null`）、`error`（画面に表示できる短い文言または`null`）を含みます。`last_frame_at`は受信した最後のカメラフレーム時刻です。

```bash
curl --request PUT http://127.0.0.1:8000/api/motion \
  --header 'Content-Type: application/json' \
  --data '{"enabled": false}'
```

`MOTION_MAX_RECORD_SECONDS`は、1本の動画に設定する最大時間です。`MOTION_RECORD_SECONDS`（最後の検知後に録画を続ける秒数）以上に設定してください。既定値は60秒です。`MOTION_MIN_RECORD_SECONDS`は保存する最小録画時間で、既定値は2秒です。録画終了後は`MOTION_COOLDOWN_SECONDS`の間、新たな録画を開始しません。

`MAXIMUM_VIDEO_BYTES`は、管理対象の確定済みMP4と録画中の`.part.mp4`を合わせた合計上限です。録画開始時は最大録画時間とビットレートから必要量を見積もり、容量や空きの確保が必要な場合だけ古い動画を整理します。保存本数の整理は新しい動画が確定してから行います。録画中は0.5秒ごとに空き容量を確認し、最低空き容量へ達した場合は録画を止めて、そこまでの動画を保存できるか試みます。ファイルシステムやエンコーダーが止まるまで時間がかかる場合があります。カメラ自体が応答停止した場合の終了・復旧時間は保証しません。

フレーム受信やエンコーダーが失敗した場合は、録画を停止して動体検知のエラー状態を表示します。保存先の空き容量不足や書き込み失敗も状態表示で知らせます。

ケージ内の小さく短い動きを記録したい場合は、最初は`MOTION_MINIMUM_CONSECUTIVE_FRAMES=2`に下げてください。見逃しがあるときだけ、`MOTION_THRESHOLD`を少しずつ下げるか、`MOTION_MIN_CHANGED_RATIO`を`0.10`から下げて実機映像で調整します。ケージ外の動きや照明変化による誤検知が多い場合は、次段階として検知エリア指定を追加します。

## 照明変化の除外

動体検知は、既存の低解像度映像の輝度を縦横4画素おきに調べます（640×360なら14,400点）。フレーム間の輝度差の中央値を画面全体の明るさの揺れとして差し引いてから、小領域内の変化割合を求めます。画面を`MOTION_ANALYSIS_TILE_SIZE`（既定32ピクセル）ごとの小領域へ分け、1つでも小領域内で補正後の差が`MOTION_THRESHOLD`以上となる画素の割合が`MOTION_MIN_CHANGED_RATIO`（既定10%）以上なら、通常の動きの候補です。

補正前の差も`MOTION_THRESHOLD`以上であることを必須とし、小さな逆方向のちらつきを補正によって増幅して候補にすることはありません。同じ小領域で`MOTION_MINIMUM_CONSECUTIVE_FRAMES`回続けて候補となったときに検知が成立します。毎回別の領域で発生したノイズは合算しません。小さな動きが領域の境界を素早く横切る場合などは見逃す可能性があるため、実際の撮影対象で確認してください。

一方で、補正前に`MOTION_ILLUMINATION_CHANGED_RATIO`以上の画素が変化し、そのうち`MOTION_ILLUMINATION_DIRECTION_RATIO`以上が同時に明るくなる、または暗くなる場合は、照明ON/OFF・カーテン・自動露出などによる全体的な明るさ変化として除外します。検出後は`MOTION_SETTLE_SECONDS`の間、新規録画を開始せず、直後の露出調整による連続誤検知を防ぎます。起動時・検知再開時の最初のフレームからも同じ秒数だけ待機します。

既定値は、全体の65%以上が同方向へ変化した場合に照明変化と判断し、5秒間待機します。ケージ内のヤモリ向けには、まず`MOTION_ANALYSIS_TILE_SIZE=32`、`MOTION_MIN_CHANGED_RATIO=0.10`、`MOTION_MINIMUM_CONSECUTIVE_FRAMES=2`で試してください。画角にケージ外が大きく入る場合の検知エリア指定は、別の機能として追加できます。

## 周期的に録画される場合の確認

既定では検知が続くと最大60秒まで録画を延長し、その後30秒待機します。そのため、約90秒間隔で約60〜61秒の動画が作られる現象は、繰り返し検知が成立している場合の挙動と一致します。停止処理にかかる時間も動画の表示時間に含まれます。90秒ごとに無条件で録画するタイマーはありません。録画中という表示自体は現在の検知成立を意味せず、最後の検知から20秒間の録画継続中も表示されます。

ライブ映像の「検知箇所・判定理由を確認」を開きます。

表示が「判定を待っています」などの初期文言のまま変わらない場合は、検知精度より先に画面の更新を確認してください。JavaScriptが動いていない、古いJavaScriptがキャッシュされている、といった可能性があります。強制再読み込みまたはプライベートウィンドウで確認します。アプリはCSS・JavaScriptの内容に応じたURLを生成して更新時に古いキャッシュを避け、画面と動体検知APIにもキャッシュ制御を指定します。「サーバーから判定情報が返されていません」と表示される場合は、サービスが更新したコードのディレクトリを参照しているか、更新後に再起動したかを確認してください。

1. 「現在の判定」で、黄色の候補領域・赤色の連続検知領域と判定理由を確認します。最大領域変化は明るさ補正後の割合、全体変化は補正前の割合です。画素差の閾値・変化割合・必要な連続回数には実際の設定値を表示します。
2. 「直近の録画開始時」へ切り替えると、最後に録画を開始した判定と位置を確認できます。記録はメモリに1件だけ保持し、再起動すると消えます。枠を重ねる映像は現在のライブ映像であり、録画開始時の静止画ではありません。表示された判定時刻も確認してください。
3. 無人の状態で数分確認し、次に撮影対象を動かして検知・録画するかを確認します。暗部だけに枠が出続ける場合は、`MOTION_THRESHOLD`を少しずつ上げるか、`MOTION_MIN_CHANGED_RATIO`を上げて再確認します。短いノイズなら連続回数を増やす方法もあります。感度を下げると小さな動きも見逃すため、1項目ずつ変更してください。

枠はパネルを開いているときだけ約1秒ごとに取得した判定で更新します。MJPEG映像と別の通信のため、完全な時刻同期はありません。追加のカメラ取得・画像変換・画像保存は行わず、枠はブラウザー側で描きます。録画開始時の最大領域変化・明るさ補正量・連続回数はINFOログにも残します。

画面全体の明るさ補正では、場所によって異なるLEDの縞状のちらつき、暗部の大きなノイズ、反射などをすべて除去できません。また、画面の大部分を占める被写体の明るさ変化も補正される場合があります。物体認識ではないため、検知枠と実際の動きを見比べて調整してください。設定は`sudoedit /etc/raspi-camera-web.env`で編集し、`sudo systemctl restart raspi-camera-web`で反映します。実機での画質・検知精度・Pi 3Bの負荷確認が必要です。

## systemd設定

```bash
uv run --no-sync python scripts/configure_systemd.py \
  --camera-backend picamera2 \
  --enable-now
```

動画の本数・容量など保存先パス以外の変更は、`sudoedit /etc/raspi-camera-web.env`で必要な値を編集して、systemdサービスを再起動してください。`VIDEO_DIR`を変更するときはディレクトリの所有者とunitの`ReadWritePaths`も変更します。`configure_systemd.py --force --reset-settings`は未指定項目を既定値に戻すため、設定を再生成する場合はバックアップ、全オプションの指定、`--dry-run`差分確認を行います。

動画の保存先は写真とは分離し、サービス実行ユーザーだけが書き込めるようにします。設定スクリプトは動画用の環境変数と、Picamera2用の`PYTHONPATH`を生成します。

## 動作確認

1. アプリ起動後に`/stream.mjpg`を開き、映像とCPU使用量を確認する。
2. カメラ前で動き、`data/videos/`にMP4が作成されること、ブラウザーで再生できることを確認する。
3. 誤検知、検知後の録画長、保存上限、数時間の連続稼働を確認する。
4. `sudo systemctl restart raspi-camera-web.service`後に映像と録画が復旧することを確認する。

実機確認の前に、解像度やフレームレートを上げないでください。OpenCVによる解析や人物検出を追加する場合は、別途Pi 3Bでの負荷測定を行います。
