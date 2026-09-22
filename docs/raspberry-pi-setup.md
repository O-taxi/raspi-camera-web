---
title: Raspberry Piとカメラのセットアップ
description: USBカメラとCSIカメラの導入、systemd登録手順
---

# Raspberry Piとカメラのセットアップ

## 対象環境

- Raspberry Pi 3B
- Raspberry Pi OS Lite 32-bit
- Python 3.9以上
- Video4Linux2対応USBカメラ、またはリボンケーブル接続のRaspberry Piカメラモジュール
- 実行ユーザー `<your-user>`

Raspbian GNU/Linux 9 (Stretch) は対象外です。新しいmicroSDへ現行のRaspberry Pi OS Liteをクリーンインストールし、元のSDカードは移行が完了するまで保管してください。メジャーバージョンをまたぐインプレース更新は行いません。

Pi 3Bはメモリが限られるため、この用途ではデスクトップ環境を含まない32-bit Lite版を推奨します。

公式のOSインストール手順：<https://www.raspberrypi.com/documentation/computers/os.html#install-using-imager>

Raspberry Pi Imagerの事前設定で、ホスト名、ユーザー名、Wi-Fi、SSH公開鍵を設定しておくと、初回からヘッドレスで接続できます。

## OSとUSBカメラの準備

```bash
sudo apt update
sudo apt full-upgrade
sudo apt install fswebcam python3 v4l-utils git curl
sudo reboot
```

再接続後、カメラが認識されていることを確認します。

```bash
uv run python scripts/check_usb_camera.py --device /dev/video0
v4l2-ctl --list-devices
ls -l /dev/video*
```

診断スクリプトが終了コード0と`OK`を返せば、指定したデバイスはUSB接続かつ撮影可能なV4L2デバイスとして認識されています。`NG`の場合は、表示されたデバイスの存在、権限、撮影機能を確認してください。

複数の `/dev/video*` がある場合は、次のコマンドで撮影可能なデバイスを確認します。

```bash
v4l2-ctl --device /dev/video0 --all
```

テスト撮影します。

```bash
fswebcam --device /dev/video0 --resolution 1280x720 --no-banner test.jpg
```

`test.jpg` が正常なら削除して構いません。サービスユーザーがカメラへアクセスできない場合は、所属グループを確認します。

```bash
groups
ls -l /dev/video0
```

必要な場合だけ `video` グループへ追加し、ログインし直します。

```bash
sudo usermod -aG video <your-user>
```

## CSI接続の Raspberry Pi カメラモジュール

Raspberry Piカメラモジュールは、カメラ用リボンケーブルを基板のCSIコネクターへ接続して使用します。電源を切った状態で接続し、ケーブルの向きは使用するPiとカメラモジュールの公式資料で確認してください。

現行のRaspberry Pi OSでは`rpicam-still`を使用します。OSを更新後、コマンドがない場合はカメラアプリを導入します。

```bash
sudo apt update
sudo apt install rpicam-apps
rpicam-still --list-cameras
rpicam-still --nopreview --width 1280 --height 720 --timeout 1000 --output test.jpg
file test.jpg
```

アプリ用の簡易診断では、カメラ認識だけ、または実際のJPEG撮影までを確認できます。テスト画像は一時ディレクトリに保存後、自動削除されます。

```bash
uv run --no-sync python scripts/check_csi_camera.py
uv run --no-sync python scripts/check_csi_camera.py --capture
```

`test.jpg`を確認後、削除して構いません。アプリは次の設定で起動します。CSIカメラでは`CAMERA_DEVICE`を使用しません。

```bash
CAMERA_BACKEND=rpicam \
CAMERA_COMMAND=rpicam-still \
CAMERA_WIDTH=1280 \
CAMERA_HEIGHT=720 \
CAMERA_CAPTURE_DELAY_MS=1000 \
uv run --no-sync uvicorn app.main:app --host 127.0.0.1 --port 8000
```

古いRaspberry Pi OSで`rpicam-still`ではなく`libcamera-still`が提供される場合は、同じバックエンドのままコマンドだけ切り替えます。

```bash
CAMERA_BACKEND=rpicam CAMERA_COMMAND=libcamera-still \
uv run --no-sync uvicorn app.main:app --host 127.0.0.1 --port 8000
```

カメラが一覧に出ない場合は、リボンケーブルの接続、カメラモジュールとの互換性、Raspberry Pi OSを確認します。`/dev/video0`の有無や`video`グループはCSIカメラの判定には使いません。

ライブ映像や動体検知録画を使う場合は、[動画・動体検知の運用]({{ '/video-and-motion.html' | relative_url }})に従ってPicamera2を準備します。

## Raspberry Pi上で写真を見る

ヘッドレスのPiでは、Tailscale Serve経由でこのアプリをブラウザーから開く方法を推奨します。撮影履歴から画像を選択でき、PiにGUIや画像ビューアーを追加する必要はありません。

Piにデスクトップ画面が接続されている場合は、軽量な`feh`を必要なときだけ導入して表示できます。`x11-utils`には画像ビューアーは含まれず、`xdg-open`もデスクトップ上の関連付け済みビューアーを起動するだけです。

```bash
sudo apt install feh
feh data/photos/<photo-id>.jpg
```

SSHだけで接続している場合は、閲覧端末へコピーしてローカルのビューアーで開きます。

```bash
scp <your-user>@<raspi-host>:/home/<your-user>/raspi-camera-web/data/photos/<photo-id>.jpg .
```

## アプリを配置

Raspberry Piで使用するログインユーザー（以降 `<your-user>`）で、リポジトリをホームディレクトリへ配置します。以下の `<your-user>` は実際のユーザー名に置き換えてください。

```bash
cd /home/<your-user>
git clone <repository-url> raspi-camera-web
cd raspi-camera-web
./scripts/install_raspberry_pi_dependencies.sh
```

このスクリプトは、USB／CSIカメラ用APTパッケージ、uv、ロック済みPython依存関係を導入します。Tailscaleの導入とtailnet認証は含めず、[Tailscale Serve設定]({{ '/tailscale-setup.html' | relative_url }})で個別に行います。

手動起動で確認します。

```bash
uvicorn app.main:app --host 127.0.0.1 --port 8000
```

別のSSH接続から確認します。

```bash
curl --fail http://127.0.0.1:8000/
```

## 実機固有の設定とsystemd登録

Git管理されるsystemd unitと`.env.example`はプレースホルダーのまま変更しません。設定スクリプトは現在のリポジトリ位置と`sudo`実行前のユーザーを検出し、次のファイルを生成します。

- `/etc/systemd/system/raspi-camera-web.service`
- `/etc/raspi-camera-web.env`

まず生成内容を確認します。この操作ではファイルを変更しません。

```bash
uv run python scripts/configure_systemd.py --dry-run
```

問題がなければ設定を生成し、サービスを有効化して起動します。

```bash
uv run python scripts/configure_systemd.py --enable-now
```

既存のunitまたは環境ファイルがある場合、スクリプトは上書きせず終了します。内容を置き換える場合だけ`--force`を追加します。

```bash
uv run python scripts/configure_systemd.py --enable-now --force
```

カメラや保存設定はコマンドライン引数で変更できます。

```bash
uv run python scripts/configure_systemd.py \
  --camera-device /dev/video2 \
  --camera-width 640 \
  --camera-height 480 \
  --maximum-photos 50 \
  --enable-now
```

CSIカメラ用の環境ファイルを生成する場合は、バックエンドとコマンドを指定します。

```bash
uv run python scripts/configure_systemd.py \
  --camera-backend rpicam \
  --camera-command rpicam-still \
  --camera-capture-delay-ms 1000 \
  --enable-now
```

指定可能な設定は`uv run python scripts/configure_systemd.py --help`で確認できます。書き込みが必要な処理だけスクリプトから`sudo`を呼び出します。環境ファイルはroot所有のモード`0600`、unitはモード`0644`で作成されます。写真ディレクトリも作成し、サービス実行ユーザーが所有するよう設定します。unitはuvの一時キャッシュをサービス専用の`/run/raspi-camera-web/`へ置くため、ホームディレクトリを読み取り専用に保ったまま起動できます。

状態とログを確認します。

```bash
systemctl status raspi-camera-web.service
journalctl -u raspi-camera-web.service -n 100 --no-pager
curl --fail http://127.0.0.1:8000/
```

アプリが起動したら、[Tailscale Serve設定]({{ '/tailscale-setup.html' | relative_url }})へ進みます。

## 更新

```bash
cd /home/<your-user>/raspi-camera-web
git pull --ff-only
uv sync --python /usr/bin/python3 --no-python-downloads --no-dev --locked
sudo systemctl restart raspi-camera-web.service
```

更新後はログ、トップページ、撮影、画像表示を確認します。

Pi 3Bの32-bit Linux（armv7）はuvのTier 2対応です。実機ではOS付属Pythonを明示的に使用し、uvによるPythonの自動ダウンロードを無効にします。WSL開発環境ではuv管理のPythonを使用します。

uvの対応プラットフォーム：<https://docs.astral.sh/uv/reference/policies/platforms/>
