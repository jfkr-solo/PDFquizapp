# Supabase のセットアップ（STEP 8）

Supabaseを使うと、学習履歴がスマホとPCで共有され、データベース上でも正答率を集計できます。使わない場合も、アプリはブラウザ内の保存だけで動きます。

## 1. プロジェクトを作る
1. https://supabase.com でプロジェクトを作る（Freeプランで可）
2. **Project Settings → API** で次の3つを控える
   - Project URL
   - `anon` public キー（アプリ用。公開してよい）
   - `service_role` キー（取り込み専用。**ブラウザやGitには絶対に入れない**）

## 2. テーブルを作る
**SQL Editor** に `supabase/migrations/20261107000000_init.sql` の中身を貼り付けて実行します（Supabase CLIを使う場合は `supabase db push`）。

作られるもの:

| テーブル | 内容 | 読み書きできる人 |
| --- | --- | --- |
| `books` / `book_versions` / `questions` | 問題集・版・問題（教材JSONの1問ずつ） | ログインユーザーは読むだけ。書き込みは取り込みスクリプトのみ |
| `answer_logs` | 1回答＝1行（追記のみ、書き換え不可） | 本人だけ |
| `question_stats` | 問題ごとの回答数・正答数・最終回答（トリガーで自動更新、間隔反復用の列あり） | 本人だけ読める |
| `study_sessions` | 途中の模擬試験などの再開用 | 本人だけ |
| `v_accuracy_by_category` / `v_accuracy_by_chapter` | 分野別・章別の正答率 | 本人の分だけ |
| Storage `book-json`（非公開） | 取り込んだ book.json のバックアップ | 取り込みスクリプトのみ |

## 3. ログイン（メールのリンク）を設定する
**Authentication → URL Configuration** の Site URL と Redirect URLs に、アプリのURL（例: `https://あなたのアプリ.vercel.app`、開発中は `http://localhost:3000`）を入れます。

## 4. 問題集を取り込む
プロジェクト直下の `.env` に書きます（`.env.example` 参照）。

```bash
SUPABASE_URL=https://xxxx.supabase.co
SUPABASE_SERVICE_ROLE_KEY=（service_role キー）
```

```bash
python -m pipeline.cli publish SAMPLE01
# → Supabaseに取り込みました: SAMPLE01 v1.0（6問、うち出題可能 6問）
```

回答ログは問題集の取り込みが前提です（`answer_logs.book_id` が `books` を参照）。取り込む前の問題集で解いた回答は端末に残り、取り込み後に自動で送信されます。

## 5. アプリに設定する
`web/.env.local`（Vercelなら Environment Variables）に書きます。

```bash
NEXT_PUBLIC_SUPABASE_URL=https://xxxx.supabase.co
NEXT_PUBLIC_SUPABASE_ANON_KEY=（anon キー）
```

トップ画面にログイン欄が出ます。ログインすると、問題集を開くたびに未送信の履歴を送り、他の端末の履歴と途中のセッションを取り込みます。オフラインで解いた分は端末に残り、次に開いたときに送信されます。

## ローカルでの検証
`supabase/tests/rls_test.sql` は、素のPostgreSQLでテーブル定義・トリガー・RLSを確かめるテストです（Supabase固有の部分は `supabase_stub.sql` で代用）。

```bash
createdb t && psql -d t -f supabase/tests/supabase_stub.sql -f supabase/migrations/20261107000000_init.sql
psql -d t -v ON_ERROR_STOP=1 -f supabase/tests/rls_test.sql   # 最後に ALL OK
```
