---
title: GitHub Pagesでの公開
description: 公開ドキュメントサイトの設定と公開範囲
---

# GitHub Pagesでの公開

このリポジトリの`docs/`は、GitHub Pagesで公開する静的ドキュメントサイトです。JekyllがMarkdownをHTMLへ変換するため、Node.jsやPi上のビルド処理は必要ありません。

## 初回設定

リポジトリの管理者がGitHubで次を設定します。

1. **Settings** → **Pages** を開く。
2. **Build and deployment** のSourceで **Deploy from a branch** を選ぶ。
3. Branchに`main`、Folderに`/docs`を選び、保存する。
4. 表示されたGitHub Pages URLを開き、公開を確認する。

`main`の`docs/`を更新すると、GitHub PagesがJekyllでHTMLを生成して公開します。

## 公開するものとしないもの

公開対象は、セットアップ、運用、開発の一般的な手順です。カメラアプリそのものはGitHub Pagesで動かさず、引き続きRaspberry Piの`127.0.0.1:8000`で待ち受け、Tailscale Serve経由だけで利用します。

次は公開しません。

- 写真、動画、ライブ映像
- 実際のPiのホスト名、Tailscale URL、tailnet名、IPアドレス
- 認証キー、トークン、Cookie、個人情報
- 利用中の機器を特定できる設置情報

公開前には、追加・変更した文書にこれらが含まれていないことを確認してください。
