---
title: ドキュメント
description: raspi-camera-webのセットアップと運用手順
---

# raspi-camera-web

Raspberry Piに接続したカメラを、Tailscale内から操作するWebアプリの公開ドキュメントです。

このサイトはセットアップ・運用・開発情報だけを公開します。カメラ映像、写真、動画、端末の実名、tailnet名、認証情報は掲載しません。

## はじめに

1. [Raspberry Piとカメラのセットアップ]({{ '/raspberry-pi-setup.html' | relative_url }})
2. [Tailscale Serve設定]({{ '/tailscale-setup.html' | relative_url }})
3. CSIカメラでライブ映像や動体検知を使う場合は、[動画・動体検知録画]({{ '/video-and-motion.html' | relative_url }})

## ドキュメント

- [機能・API・設定仕様]({{ '/specification.html' | relative_url }})
- [Raspberry Piとカメラのセットアップ]({{ '/raspberry-pi-setup.html' | relative_url }})
- [ライブ映像と動体検知録画]({{ '/video-and-motion.html' | relative_url }})
- [Tailscale Serve設定]({{ '/tailscale-setup.html' | relative_url }})
- [開発ガイドと実装状況]({{ '/development.html' | relative_url }})
- [GitHub Pagesでの公開]({{ '/github-pages.html' | relative_url }})

## カメラバックエンドの選び方

- **USB UVCカメラ**：`fswebcam`を使います。静止画撮影に対応し、Picamera2のライブ映像・動体検知録画には対応しません。
- **CSI接続のRaspberry Piカメラ、静止画のみ**：`rpicam`を使います。
- **CSIカメラ、ライブ映像や動体検知録画も使う**：`picamera2`を使います。カメラをPicamera2サービスが一元管理します。
- **開発・画面確認**：`mock`を使います。実カメラの動作確認にはなりません。

APIの入出力、環境変数、保存形式、画面上の動作は[機能・API・設定仕様]({{ '/specification.html' | relative_url }})にまとめています。
