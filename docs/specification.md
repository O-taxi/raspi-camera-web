---
title: 機能・API・設定仕様
description: raspi-camera-webの機能、HTTP API、設定、保存データの契約
---

# 機能・API・設定仕様

## 目次

- [機能](#機能)
- [HTTP API](#http-api)
- [日時の意味](#日時の意味)
- [環境変数](#環境変数)
- [保存データと画面の契約](#保存データと画面の契約)
- [関連文書](#関連文書)

## 機能

| バックエンド | カメラ | 静止画 | ライブ映像 | 動体検知録画 |
| --- | --- | --- | --- | --- |
| `fswebcam` | USB V4L2 | 対応 | 非対応 | 非対応 |
| `rpicam` | CSI | 対応 | 非対応 | 非対応 |
| `picamera2` | CSI | 対応 | 対応 | 対応 |
| `mock` | なし | 開発用 | 非対応 | 非対応 |

ブラウザー画面は写真撮影、写真履歴の表示・削除に対応します。Picamera2を使う場合はライブMJPEG映像、動体検知ON/OFF、動画履歴の表示・ダウンロード・削除も表示します。写真は8件単位、動画は10件単位でページを切り替えます。

動体検知の状態は`VIDEO_DIR`内の`.motion-state.json`へ保存します。保存値が有効なら環境変数の値より優先されます。ファイルがない場合は`MOTION_ENABLED`を使います。ファイルが不正または読み取れない場合は安全側としてOFFで起動します。

停止操作は進行中の録画を破棄します。画面は確認を表示してから停止します。動体検知録画は静止画やカメラ全体を停止せず、録画用エンコーダーを終了します。録画には時間上限、管理対象動画の合計容量上限、空き容量下限を適用します。上限に近づいた録画は停止し、その時点までの動画を保存できるか試みます。フレーム取得やエンコーダーに障害が起きた場合、録画は継続できないことがあり、状態APIの`state`と`error`で利用者に示します。ハードウェアが応答を停止した場合の復旧時間は保証しません。

## HTTP API

アプリは既定で`127.0.0.1:8000`に待ち受けます。URLパスや応答形式は次の通りです。クライアントはファイルパスや撮影コマンドを渡しません。

| メソッド・パス | 成功応答 | 主なエラー |
| --- | --- | --- |
| `POST /api/capture` | `200`, 写真オブジェクト | `403` クロスサイト要求、`429` 撮影中・連打制限、`503` カメラ失敗・タイムアウト・保存不可 |
| `GET /api/photos` | `200`, 写真オブジェクトの配列 | — |
| `GET /photos/{photo_id}` | `200`, `image/jpeg` | `404` ID不正または写真なし |
| `DELETE /api/photos/{photo_id}` | `204` 空応答 | `403` クロスサイト要求、`404` 写真なし |
| `GET /stream.mjpg` | `200`, multipart MJPEG | `404` Picamera2未使用 |
| `GET /api/motion` | `200`, 動体検知状態 | `404` Picamera2未使用 |
| `PUT /api/motion` | `200`, 更新後の動体検知状態 | `403` クロスサイト要求、`404` Picamera2未使用、`422` リクエスト形式不正、`503` 状態保存・録画停止失敗 |
| `GET /api/videos` | `200`, 動画オブジェクトの配列 | Picamera2未使用時は空配列 |
| `GET /videos/{video_id}` | `200`, `video/mp4`添付ファイル | `404` ID不正または動画なし |
| `DELETE /api/videos/{video_id}` | `204` 空応答 | `403` クロスサイト要求、`404` 動画なし |

写真と動画の各オブジェクトは次の形です。`duration_seconds`は動画だけにあり、メタデータがない場合は`null`です。

```json
{
  "id": "20260925-120000-0123abcd",
  "captured_at": "2026-09-25T12:00:00+09:00",
  "url": "/photos/20260925-120000-0123abcd"
}
```

```json
{
  "id": "20260925-120000-0123abcd",
  "captured_at": "2026-09-25T12:00:00+09:00",
  "url": "/videos/20260925-120000-0123abcd",
  "duration_seconds": 20
}
```

通常のHTTPエラー本文は`{"detail":"..."}`形式ですが、FastAPIの入力検証エラー`422`では`detail`が配列になります。内部パスや外部コマンド出力を応答に含めません。`POST /api/capture`の`429`と`503`は`Retry-After`を返し、成功時の`200`は最低撮影間隔を`X-Capture-Cooldown`で返します。

`GET /api/motion`と`PUT /api/motion`は同じ状態オブジェクトを返します。更新リクエストは`{"enabled": true}`または`{"enabled": false}`です。

```json
{
  "enabled": true,
  "state": "waiting",
  "stream_state": "streaming",
  "last_frame_at": "2026-09-25T03:00:00+00:00",
  "error": null
}
```

`state`は`disabled`（検知停止中）、`waiting`（検知待機中）、`recording`（録画中）、`cooldown`（録画後の待機中）、`error`（検知または録画のエラー）です。`stream_state`は`starting`（初期化中）、`streaming`（フレーム受信中）、`stale`（フレーム更新が止まっている）です。`last_frame_at`は最終フレーム時刻をUTCのISO 8601文字列で示し、まだフレームがなければ`null`です。`error`は画面に表示できる短いメッセージまたは`null`です。

ブラウザー要求による副作用操作は、`Sec-Fetch-Site: cross-site`を拒否します。`GET`は読み取り専用です。写真・動画一覧APIは全件のメタデータを返し、画面上のページ切り替えはブラウザー側で行います。Tailscale Serveと同じtailnetのアプリ利用者は、撮影、写真・動画の削除、動体検知の設定変更を行える権限を持ちます。アプリ内ユーザー認証や個人別権限はありません。

## 日時の意味

写真・動画の`captured_at`は撮影を開始した時刻ではなく、管理ファイルのファイルシステム更新時刻（mtime）を読み取って生成します。APIはPiのローカルタイムゾーンオフセット付きISO 8601形式で返し、ブラウザーは日時を閲覧端末のローカルタイムゾーンで表示します。ファイルを外部操作でコピーするとmtimeが変わり、表示時刻も変わる場合があります。`id`は`YYYYMMDD-HHMMSS-<8桁hex>`形式で生成する識別子で、表示時刻の代用にはしません。

## 環境変数

数値は正の値を指定します。`MOTION_*_RATIO`は0より大きく1以下です。真偽値は`1/true/yes/on`または`0/false/no/off`を受け付けます。設定不正は起動時エラーです。

| 変数 | 既定値 | 用途 |
| --- | --- | --- |
| `PHOTO_DIR` | `<project>/data/photos` | 写真保存先 |
| `CAMERA_BACKEND` | `fswebcam` | `fswebcam`、`rpicam`、`picamera2`、`mock` |
| `CAMERA_COMMAND` | バックエンドに応じたコマンド | 静止画撮影コマンド。`rpicam`では通常`rpicam-still` |
| `CAMERA_DEVICE` | `/dev/video0` | USBカメラのV4L2デバイス。CSIでは未使用 |
| `CAMERA_WIDTH` | `1280` | `fswebcam`と`rpicam`静止画の幅。Picamera2静止画では未使用 |
| `CAMERA_HEIGHT` | `720` | `fswebcam`と`rpicam`静止画の高さ。Picamera2静止画では未使用 |
| `CAPTURE_TIMEOUT_SECONDS` | `15` | 静止画撮影タイムアウト |
| `CAMERA_CAPTURE_DELAY_MS` | `1000` | `rpicam`静止画でカメラ起動後に待つ時間。ほかのバックエンドでは未使用 |
| `MINIMUM_CAPTURE_INTERVAL_SECONDS` | `5` | 写真撮影の最小間隔 |
| `MAXIMUM_PHOTOS` | `100` | 保存する写真の最大枚数 |
| `VIDEO_DIR` | `<project>/data/videos` | 動画と動体検知状態の保存先 |
| `MAXIMUM_VIDEOS` | `20` | 保存する動画の最大本数 |
| `MAXIMUM_VIDEO_BYTES` | `500000000` | 管理中の確定済みMP4と録画中`.part.mp4`を合わせた合計最大バイト数 |
| `MINIMUM_FREE_DISK_BYTES` | `100000000` | 録画開始に必要な最低空きバイト数。保存先の空きを保つしきい値 |
| `VIDEO_WIDTH` | `1280` | 録画映像の幅 |
| `VIDEO_HEIGHT` | `720` | 録画映像の高さ |
| `VIDEO_FPS` | `15` | 録画フレームレート |
| `VIDEO_BITRATE` | `2000000` | H.264録画ビットレート |
| `LIVE_STREAM_WIDTH` | `640` | ライブ映像と動体解析の幅 |
| `LIVE_STREAM_HEIGHT` | `360` | ライブ映像と動体解析の高さ |
| `LIVE_STREAM_FPS` | `5` | ライブ映像のフレームレート |
| `MOTION_THRESHOLD` | `12.0` | 輝度差の検知しきい値 |
| `MOTION_ANALYSIS_TILE_SIZE` | `32` | 動体解析領域の一辺（ピクセル） |
| `MOTION_MIN_CHANGED_RATIO` | `0.10` | 1領域内で必要な変化画素の割合 |
| `MOTION_ILLUMINATION_CHANGED_RATIO` | `0.65` | 全体照明変化とみなす変化割合 |
| `MOTION_ILLUMINATION_DIRECTION_RATIO` | `0.90` | 同じ方向へ変化した画素の割合 |
| `MOTION_SETTLE_SECONDS` | `5` | 全体照明変化の後に検知を再開するまでの秒数 |
| `MOTION_MINIMUM_CONSECUTIVE_FRAMES` | `3` | 検知成立に必要な連続フレーム数 |
| `MOTION_RECORD_SECONDS` | `20` | 最後の検知後に録画を続ける秒数 |
| `MOTION_MIN_RECORD_SECONDS` | `2` | 保存する最小録画時間 |
| `MOTION_MAX_RECORD_SECONDS` | `60` | 1本の録画の最大時間 |
| `MOTION_COOLDOWN_SECONDS` | `30` | 録画後に次の録画を始めない秒数 |
| `MOTION_ENABLED` | `true` | 保存状態ファイルがない場合の初期状態 |
| `MOTION_STATE_PATH` | `<VIDEO_DIR>/.motion-state.json` | 動体検知ON/OFFの永続化ファイル。systemdでは書き込み許可のある`VIDEO_DIR`内へ置く |
| `PYTHONPATH` | 設定なし | Picamera2利用時にOSのPythonパッケージパスを追加 |

## 保存データと画面の契約

- 写真は`PHOTO_DIR/<id>.jpg`、動画は`VIDEO_DIR/<id>.mp4`として保存します。画像・動画・IDはクライアントからの任意パスで解決せず、形式検証後に管理対象ディレクトリから検索します。
- 写真・動画とも新しいものを先に一覧し、上限を超えた古いファイルを整理します。録画開始時には必要容量を見積もり、合計バイト上限と空き容量条件を満たすために必要な場合だけ古い動画を整理します。本数上限による整理は新しい録画の確定後に行います。録画中は0.5秒ごとに容量を確認し、空き容量条件へ達すると録画を止めて現在の動画の保存を試みます。エンコーダーやファイルシステムの停止が遅れると終了に時間がかかり、保存できない場合があります。動画の再生時間メタデータは`VIDEO_DIR/.video-metadata.json`で管理します。
- 録画中ファイルは`<id>.part.mp4`という一時名を使い、正常終了後に`.mp4`へ確定します。起動時は管理対象の`*.part.mp4`を削除します。
- 状態ファイル、動画メタデータ、一時録画ファイルは画面の履歴に表示しません。
- 写真履歴は拡大表示と確認後の削除に対応します。動画履歴は時間表示、ダウンロード、確認後の削除に対応します。
- ライブ映像の通常時は状態説明を表示しません。動体検知の録画中と、フレーム更新の停止や状態取得の失敗などのエラー時にのみ画面へ状態を示します。
- 全てのアプリ利用者に対し、アプリ上の写真撮影・削除、動画削除、動体検知設定変更を許可します。Tailscale側のアクセス制御で、アプリへ接続できるユーザー・端末を制限してください。

## 関連文書

- [Raspberry Piとカメラのセットアップ]({{ '/raspberry-pi-setup.html' | relative_url }})
- [ライブ映像と動体検知録画]({{ '/video-and-motion.html' | relative_url }})
- [Tailscale Serve設定]({{ '/tailscale-setup.html' | relative_url }})
