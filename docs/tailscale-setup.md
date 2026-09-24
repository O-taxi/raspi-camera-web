---
title: Tailscale Serve設定
description: Tailscale内だけでカメラアプリへ接続する手順
---

# Tailscale Serve設定

## 目次

- [前提](#前提)
- [Raspberry Piへインストール](#raspberry-piへインストール)
- [Serveを設定](#serveを設定)
- [閲覧端末](#閲覧端末)
- [停止と再設定](#停止と再設定)
- [アクセス制御](#アクセス制御)
- [運用上の注意](#運用上の注意)
- [トラブルシューティング](#トラブルシューティング)

この文書では、Raspberry Pi上のWebアプリを同じtailnetの端末だけにHTTPSで公開する手順を扱います。

## 前提

- Raspberry Pi上のアプリが `127.0.0.1:8000` で起動している
- Raspberry Piと閲覧端末が同じTailscaleアカウントまたはtailnetへ参加している
- MagicDNSとHTTPS証明書が有効になっている
- Tailscale Funnelを使用しない

実際のtailnet名、認証キー、端末固有情報はリポジトリへ記録しないでください。

## Raspberry Piへインストール

Tailscaleの公式Linux向け手順に従ってインストールします。

- <https://tailscale.com/download/linux>

インストール後、Piをtailnetへ参加させます。

```bash
sudo tailscale up
```

表示されたURLをブラウザーで開き、利用するアカウントで認証します。状態を確認します。

```bash
tailscale status
```

## Serveを設定

Webアプリを起動し、Pi自身から応答を確認します。

```bash
curl --fail http://127.0.0.1:8000/
```

続いて、Tailscale Serveからローカルアプリへ転送します。

```bash
sudo tailscale serve --bg 8000
```

TailscaleのバージョンによってCLI構文が変わる可能性があるため、失敗した場合は先にヘルプを確認します。

```bash
tailscale serve --help
```

設定結果を確認します。

```bash
tailscale serve status
```

出力された次の形式のURLへ、許可されたTailscale端末からアクセスします。この形式と山括弧のプレースホルダーは一般向け文書に記載できます。実際のマシン名やtailnet名を含むURLは非公開情報として扱い、GitHub Pages、README、公開Issueへ載せず、利用者へはtailnet内のブックマーク等で個別共有してください。

```text
https://<raspiのマシン名>.<tailnet名>.ts.net/
```

初回はHTTPS証明書を有効にするための確認画面が表示される場合があります。

公式ドキュメント：<https://tailscale.com/docs/features/tailscale-serve>

## 閲覧端末

PCまたはスマートフォンへTailscaleをインストールし、Piと同じtailnetへ参加させます。

- <https://tailscale.com/download>

Tailscaleが接続状態になってから、ServeのHTTPS URLを開きます。GitHub Pagesや他の公開文書には実URLを載せません。公開文書には一般的な接続手順だけを置き、実URLはtailnet内のブックマークや限定された連絡手段で共有します。

## 停止と再設定

現在のServe設定を停止する場合：

```bash
sudo tailscale serve reset
```

再設定後は、意図せずFunnelが有効になっていないことも確認します。

```bash
tailscale serve status
tailscale funnel status
```

Funnelを誤って有効にした場合は停止します。

```bash
sudo tailscale funnel reset
```

## アクセス制御

アプリ自身は利用者ごとの認証・権限分けを行いません。Serve URLへ到達できる利用者は、写真撮影、写真・動画の削除、動体検知設定の変更を行えます。共有対象を選ぶときはこの権限を含めて判断してください。

アクセス可能なユーザーと端末は、tailnet policyのgrantsまたはACLでPiへのHTTPS接続に限定します。必要な接続元、対象端末、ポートを確認して設定してください。ルールの記法と適用範囲は[Tailscale Access controlの公式資料](https://tailscale.com/docs/features/access-control)を参照します。ServeのURLを知っているだけではアクセス権を与えず、tailnetのポリシーを接続制御の正本とします。

## 運用上の注意

- ルーターの80、443、22番ポートを転送しない。
- Uvicornを `0.0.0.0` へ公開せず、`127.0.0.1` だけで待ち受ける。
- tailnetへの参加ユーザーと端末を定期的に確認する。
- 不要になった端末はTailscale管理画面から削除する。
- tailnet policyで、許可したユーザー・端末からPiのServeへ到達できることを確認する。
- 公開共有が必要になっても、カメラ用途では安易にFunnelへ切り替えず、認証設計を先に見直す。

## トラブルシューティング

アプリがローカルで待ち受けているか確認します。

```bash
ss -ltnp | grep 8000
curl --fail http://127.0.0.1:8000/
```

TailscaleとServeの状態を確認します。

```bash
tailscale status
tailscale serve status
```

名前解決できない場合は、Tailscale管理画面でMagicDNSが有効か確認します。閲覧端末側でもTailscaleが接続済みであることを確認してください。
