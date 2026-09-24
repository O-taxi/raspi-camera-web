---
title: Raspberry Piとカメラのセットアップ
description: Raspberry Pi、カメラ、systemdの導入手順
---

# Raspberry Piとカメラのセットアップ

## 目次

- [対象環境](#対象環境)
- [OSの準備](#osの準備)
- [uvとアプリの準備](#uvとアプリの準備)
- [カメラの接続と診断](#カメラの接続と診断)
- [バックエンドを選んで手動起動](#バックエンドを選んで手動起動)
- [systemdへの登録](#systemdへの登録)
- [写真を閲覧する](#写真を閲覧する)
- [アプリの更新](#アプリの更新)

## 対象環境

- Raspberry Pi 3B
- Raspberry Pi OS Lite 32-bit
- Python 3.9以上
- Video4Linux2対応USBカメラ、またはリボンケーブル接続のRaspberry Piカメラ
- 実行ユーザー`<your-user>`

Raspbian GNU/Linux 9 (Stretch) は対象外です。新しいmicroSDへ現行のRaspberry Pi OS Liteをクリーンインストールし、元のSDカードは移行が完了するまで保管してください。メジャーバージョンをまたぐインプレース更新は行いません。Pi 3Bではデスクトップ環境を含まない32-bit Lite版を推奨します。

OSの公式インストール手順：<https://www.raspberrypi.com/documentation/computers/os.html#install-using-imager>

## OSの準備

Raspberry Pi OS上で、このアプリ専用に用意したroot以外の一般ユーザーとして実行します。

```bash
sudo apt update
sudo apt full-upgrade
sudo apt install git curl file python3 v4l-utils
sudo reboot
```

再起動後、ホームディレクトリへアプリを配置します。

## uvとアプリの準備

`<your-user>`と`<repository-url>`を環境に合わせて置き換えます。インストールスクリプトがカメラ用APTパッケージ、uv、ロック済みPython依存関係を導入します。最初にuvを手動で導入する必要はありません。

```bash
cd /home/<your-user>
git clone <repository-url> raspi-camera-web
cd raspi-camera-web
./scripts/install_raspberry_pi_dependencies.sh
```

スクリプトは実行ユーザーを`video`グループへ追加します。グループ変更とインストーラーが加えたPATHの設定を反映するため、**USB/CSIどちらを使う場合もログアウトして再ログイン**してください。その後、プロジェクトディレクトリへ戻ります。

Pi上の診断・管理スクリプトとUvicornは、OS付属Pythonで同期済みの環境を使う`uv run --no-sync`で起動します。開発用PythonをPiへダウンロードしたり、依存を再同期したりしません。

## カメラの接続と診断

アプリ起動前に、選んだハードウェアをOSのツールで診断します。

### USBカメラ

カメラをUSB接続し、撮影可能なV4L2デバイスを確認します。

```bash
v4l2-ctl --list-devices
ls -l /dev/video*
uv run --no-sync python scripts/check_usb_camera.py --device /dev/video0
```

診断スクリプトが終了コード0と`OK`を返すことを確認します。`NG`の場合はデバイス番号、権限、撮影機能を確認してください。複数の`/dev/video*`がある場合は`--device`に正しい番号を指定します。

アプリと同じ撮影コマンドでテストします。

```bash
fswebcam --device /dev/video0 --resolution 1280x720 --no-banner /tmp/raspi-camera-test.jpg
file /tmp/raspi-camera-test.jpg
```

JPEGとして保存できたことを確認します。USBカメラが使えない場合は、`groups`と`ls -l /dev/video0`で権限を調べ、必要な場合だけ`sudo usermod -aG video <your-user>`を実行して再ログインします。

### CSIカメラ

カメラ用リボンケーブルは電源を切ってから接続します。コネクターとケーブルの向きは使用中のPiとカメラモジュールの公式資料で確認してください。

現行のRaspberry Pi OSでは`rpicam-still`を使います。旧OSで`libcamera-still`だけが提供される場合は、以下の`rpicam-still`を`libcamera-still`へ、`rpicam-hello`を`libcamera-hello`へ読み替えます。どちらもなければカメラ用APTパッケージを確認してから、OS付属のツールで認識とJPEG撮影を確認します。

```bash
rpicam-still --list-cameras
rpicam-still --nopreview --width 1280 --height 720 --timeout 1000 --output /tmp/raspi-camera-test.jpg
file /tmp/raspi-camera-test.jpg
uv run --no-sync python scripts/check_csi_camera.py --capture
```

CSIカメラでは`/dev/video0`や`CAMERA_DEVICE`を使いません。カメラが一覧に出ない場合は、ケーブル接続、モジュールとの互換性、Raspberry Pi OSを確認してください。Picamera2を使う場合も、ここで認識とテスト撮影が成功してからアプリを起動します。

## バックエンドを選んで手動起動

必要な診断を済ませた後、利用方法に合うバックエンドで起動します。どの例も`127.0.0.1:8000`だけで待ち受けます。

### USBカメラで静止画

```bash
CAMERA_BACKEND=fswebcam CAMERA_DEVICE=/dev/video0 \
uv run --no-sync uvicorn app.main:app --host 127.0.0.1 --port 8000
```

### CSIカメラで静止画

```bash
CAMERA_BACKEND=rpicam CAMERA_COMMAND=rpicam-still \
uv run --no-sync uvicorn app.main:app --host 127.0.0.1 --port 8000
```

古いRaspberry Pi OSが`rpicam-still`ではなく`libcamera-still`を提供する場合は、`CAMERA_COMMAND=libcamera-still`にします。

### CSIカメラでライブ映像・動体検知録画

```bash
PYTHONPATH=/usr/lib/python3/dist-packages CAMERA_BACKEND=picamera2 \
uv run --no-sync uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Picamera2では静止画も同じサービスから撮影するため、`rpicam-still`など別のカメラプロセスを同時に起動しません。録画設定は[ライブ映像と動体検知録画]({{ '/video-and-motion.html' | relative_url }})を参照してください。

別のSSH接続から応答を確認します。

```bash
curl --fail http://127.0.0.1:8000/
```

画面の撮影と画像表示を確認したら、systemdへ切り替える前に手動Uvicornを`Ctrl+C`で終了します。手動プロセスとsystemdサービスは同じポートを同時に使用できません。

## systemdへの登録

設定スクリプトは実際のリポジトリ位置とログインユーザーを使い、次のファイルを生成します。

- `/etc/systemd/system/raspi-camera-web.service`
- `/etc/raspi-camera-web.env`

初回は生成内容を確認し、対象ファイルがまだないことを確認してから有効化・起動します。

```bash
uv run --no-sync python scripts/configure_systemd.py --dry-run --camera-backend fswebcam
uv run --no-sync python scripts/configure_systemd.py --enable-now --camera-backend fswebcam
```

CSI静止画なら`--camera-backend rpicam --camera-command rpicam-still`、Picamera2なら`--camera-backend picamera2`を指定します。オプションは`uv run --no-sync python scripts/configure_systemd.py --help`で確認できます。生成スクリプトは必要な書き込み処理だけsudoで行い、サービスはroot以外のログインユーザーで動きます。

写真・動画の保存パス以外の設定を変える場合は、`sudoedit /etc/raspi-camera-web.env`で必要な値だけを編集し、`sudo systemctl restart raspi-camera-web.service`を実行します。`PHOTO_DIR`や`VIDEO_DIR`を変更するときは、ディレクトリ所有者とsystemd unitの`ReadWritePaths`も合わせる必要があります。設定生成をやり直すか、unit overrideを用いて保存先の準備と書き込み許可を設定してください。

既存設定を再生成する場合、`--force --reset-settings`は未指定設定を既定値に戻します。通常の設定変更に使わないでください。必要な場合は環境ファイルとunitを先にバックアップし、すべてのカスタム設定をオプションで指定して`--dry-run`出力を現在の内容と比較してから実行します。`--force`だけでは既存環境ファイルを上書きしません。

サービス状態とログを確認します。

```bash
systemctl status raspi-camera-web.service
journalctl -u raspi-camera-web.service -n 100 --no-pager
curl --fail http://127.0.0.1:8000/
```

Tailscale ServeからHTTPSで接続する手順は[Tailscale Serve設定]({{ '/tailscale-setup.html' | relative_url }})を参照してください。

## 写真を閲覧する

ヘッドレスのPiでは、Tailscale Serve経由でブラウザーから見る方法を推奨します。Piにデスクトップ環境や画像ビューアーを追加する必要はありません。

デスクトップへ接続している場合は、必要なときだけ`feh`を導入します。

```bash
sudo apt install feh
feh data/photos/<photo-id>.jpg
```

SSH接続のみの場合は閲覧端末へコピーします。

```bash
scp <your-user>@<raspi-host>:/home/<your-user>/raspi-camera-web/data/photos/<photo-id>.jpg .
```

## アプリの更新

コード更新と設定変更は分けて行います。コードとロック済み依存関係を更新するときは、設定生成スクリプトを再実行しません。

```bash
cd /home/<your-user>/raspi-camera-web
git pull --ff-only
uv sync --python /usr/bin/python3 --no-python-downloads --no-dev --locked
sudo systemctl restart raspi-camera-web.service
```

更新後はログ、トップページ、撮影、画像表示を確認します。設定値だけを変える場合は`sudoedit /etc/raspi-camera-web.env`で保存パス以外の値を編集し、サービスを再起動します。Pi 3Bの32-bit Linux（armv7）ではOS付属Pythonを指定し、uvによるPythonの自動ダウンロードを無効にします。

uvの対応プラットフォーム：<https://docs.astral.sh/uv/reference/policies/platforms/>
