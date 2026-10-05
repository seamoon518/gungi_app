# Claude にデプロイ先（Vercel / Railway）を触ってもらう方法

Claude Code（クラウド版）は、隔離されたコンテナの中で動いています。
初期設定では、本番サイトと Vercel / Railway の管理画面にはつながりません。
下の設定をすると、Claude が次の作業を自分でできるようになります。

| できるようになること | 必要な設定 |
|---|---|
| 本番サイトを開いて動作確認する（E2E テストを本番に向けて流す） | ① ネットワーク許可 |
| デプロイの成否・ビルドログ・エラーログを見る | ① ＋ ② トークン |
| 環境変数の変更（例: `GUNGI_FAST_ENGINE=0` で AI を元に戻す）・再デプロイ | ① ＋ ② トークン（書き込み権限つき） |

> ⚠️ 設定画面は **PC のブラウザ** で操作してください（スマホアプリからは変更できません）。
> ⚠️ トークンやパスワードは **チャットに貼らないでください**。必ず下の「環境変数」に入れてください。

---

## ① ネットワークの許可（本番サイトを見られるようにする）

1. PC のブラウザで https://claude.ai/code を開き、このプロジェクトのセッションを開く
2. 画面上部（タイトルバー）の **クラウド環境の名前** をクリック → **Edit（編集）**
3. **Network access（ネットワークアクセス）** を **Custom** にする
   - 既定で入っているパッケージマネージャ（npm・PyPI など）の許可は **そのまま残す**
4. **Allowed domains（許可するドメイン）** に次を追加して保存

   ```
   gungi-app.vercel.app
   *.vercel.app
   gungiapp-production.up.railway.app
   api.vercel.com
   backboard.railway.com
   backboard.railway.app
   ```

   | ドメイン | 用途 |
   |---|---|
   | `gungi-app.vercel.app` | 本番フロントエンド |
   | `*.vercel.app` | PR ごとのプレビュー環境 |
   | `gungiapp-production.up.railway.app` | 本番バックエンド |
   | `api.vercel.com` | Vercel の管理 API（デプロイ状況・ログ） |
   | `backboard.railway.com` / `backboard.railway.app` | Railway の管理 API（デプロイ状況・ログ・環境変数） |

5. **新しいセッションを始める**（設定は新しいセッションから有効になります）

公式の手順: https://code.claude.com/docs/en/cloud-environments#network-access

本番サイトを見るだけなら、①だけで十分です（2・3 行目と 4 行目のドメインだけでも可）。

---

## ② トークンの登録（デプロイ状況・ログを見られるようにする）

### Vercel のトークンを作る
1. https://vercel.com/account/settings/tokens を開く
2. **Create Token**
   - 名前: `claude-code` など
   - Scope: `seamoon518's projects`（このアプリのチーム）
   - 有効期限: 30日〜90日など、短めがおすすめ
3. 表示されたトークンをコピー（この画面でしか表示されません）

### Railway のトークンを作る
1. Railway のダッシュボードで gungi_app のプロジェクトを開く
2. **Settings → Tokens** で **Project Token** を作成
   - 環境: `production`
   - Project Token は、このプロジェクトのこの環境だけを操作できます（アカウント全体のトークンより安全です）
3. 表示されたトークンをコピー

### Claude の環境に登録する
1. ①と同じく、タイトルバーの環境名 → **Edit**
2. **Environment variables（環境変数）**（または「API credentials」欄）に次を追加して保存

   ```
   VERCEL_TOKEN=（Vercel のトークン）
   RAILWAY_TOKEN=（Railway の Project Token）
   ```

3. **新しいセッションを始める**

Claude はこの名前（`VERCEL_TOKEN` / `RAILWAY_TOKEN`）で読み取ります。
コードや git には一切書き込みません。

---

## 設定後に Claude へ頼めること（例）

- 「本番で E2E テストを流して」
  → `E2E_BASE_URL=https://gungi-app.vercel.app npm test` を実行します
- 「デプロイが成功したか確認して」
  → Vercel / Railway の最新デプロイの状態とビルドログを確認します
- 「本番の AI を元に戻して」
  → Railway の環境変数 `GUNGI_FAST_ENGINE=0` を設定します
  （本番の変更なので、実行前に必ず確認を取ります）

## 安全のための注意

- トークンは **期限つき・必要最小限の範囲** で作り、不要になったら各サービスの画面で削除してください
- 本番への変更（環境変数の変更・再デプロイ・マージ）は、CLAUDE.md のルールどおり **実行前に必ず確認** を取ります
- 設定をやめたいときは、環境設定からドメインと環境変数を消すだけで元に戻ります
