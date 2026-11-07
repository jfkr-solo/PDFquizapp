# 運用手順書

PDF問題集を教材として公開するまでの、毎回の作業手順と困ったときの対処をまとめます。開発環境の準備は [README](../README.md)、Supabase の初期設定は [supabase/README.md](../supabase/README.md) を参照してください。

## 全体の流れ

```text
原本PDF ─convert─▶ book.json ＋ 検証レポート ─人が確認（verify / reject）─▶ 出題できる問題
                                                                    │
                          audio（音声MP3） ◀─────────────────────────┤
                          sync-books → アプリ（web）を公開 ◀────────┤
                          publish → Supabase に取り込み ◀───────────┘
```

正解は必ず原本の解答ページから取ります。AIや推測で正解を決めることはありません。読めない部分は「要確認（pending）」になり、人が原本と照合するまで模擬試験と音声には出ません。

## 1. 新しい問題集を追加する（毎回）

作業前に次の3つを決めます。

- **問題集ID**：英数字と `-` `_` で2〜32文字。例：`IT2026A`。一度決めたら変えません。
- **タイトル**
- **原本の問題数**：目次や最終問題番号から確認します。

```bash
source .venv/bin/activate
python -m pipeline.cli convert ~/Downloads/問題集.pdf --book-id IT2026A --title "IT基礎 2026年版" --expected 300
```

- 原本PDFは `data/raw/IT2026A/source.pdf` にコピーされます。元のファイルは動かしません。
- 結果は `data/books/IT2026A/` にできます。
- 1000問でも数十秒以内に終わります（スキャンPDFのOCRは1ページ数秒かかります）。
- ルールで問題を見つけられないページがある場合だけ `--ai` を付けます。`.env` の `ANTHROPIC_API_KEY` が必要です。AIが整形した問題は必ず要確認になります。

## 2. 検証レポートを確認する

`data/books/IT2026A/validation_report.md` を開きます。冒頭の集計を見てください。

| 集計 | 意味 | すること |
| --- | --- | --- |
| 自動検証OK | 機械的なチェックをすべて通過 | 数問を抜き取って原本と見比べる |
| 要確認 | 人の確認が必要 | 下の表に従って1問ずつ確認する |
| JSON Schema | 形式エラーの有無 | エラーがあれば公開できない。parse の書式対応を直す |

よく出る指摘と対処です。

| 指摘 | 原因 | 対処 |
| --- | --- | --- |
| `COUNT_MISMATCH` | 抽出した問題数が `--expected` と違う | 欠けた番号（`NUMBER_SEQUENCE`）を見て、原本の書式を確認する |
| `ANSWER_COUNT_MISMATCH`、`NO_ANSWER` | 解答が見つからない | 原本の解答ページを確認する。読めなければ reject |
| `OPTIONS_MISSING`、`OPTIONS_GAP` | 選択肢の欠け、ページまたぎ | 原本と照合する |
| `ANSWER_NOT_IN_OPTIONS` | 解答の記号が選択肢に無い | OCRの読み違いが多い。原本と照合する |
| `EXPLANATION_CONFLICT` | 解説の内容が正解と矛盾 | 原本の誤植の可能性もある。照合する |
| `OCR_SOURCE`、`OCR_NOISE`、`GARBLED` | スキャン由来、または文字化け | 文字を1字ずつ照合する |
| `FIGURE_MISSING`、`FIGURE_AUTO_CROPPED` | 図が取れない、またはページから切り出した | 切り出した図で問題が解けるか確認する |
| `CHANGED_AFTER_VERIFY` | 確認済みの後で内容が変わった | もう一度照合する |

## 3. 人の確認を記録する

原本と照合して正しければ verify、使えなければ reject です。誰がいつ何をしたかは `validation_history` に残ります。

```bash
python -m pipeline.cli verify IT2026A IT2026A-Q0012 IT2026A-Q0013 --note "原本p.4と照合" --by koki
python -m pipeline.cli reject IT2026A IT2026A-Q0020 --note "図が判読不能" --by koki
```

- PDFを差し替えて convert し直しても、確認済みと除外の判断は引き継がれます。
- 内容が変わった問題だけ自動で要確認に戻ります。

## 4. 音声を作る（任意）

```bash
python -m pipeline.cli audio IT2026A --engine voicevox --pause 5
```

- VOICEVOX を起動しておきます。Google を使う場合は `--engine google` にし、`.env` に `GOOGLE_TTS_API_KEY` を設定します。
- 読み上げるのは出題できる問題だけです。
- 確認作業が進んだら、もう一度実行すれば増えた分だけ合成します。

## 5. アプリに反映して公開する

```bash
cd web
npm run sync-books      # data/books → public/books（音声も）
npm run build           # out/ に静的サイトができる
```

`out/` を静的ホスティング（Vercel、Netlify、Cloudflare Pages など）に置きます。

- ホスティング側の環境変数に `NEXT_PUBLIC_SUPABASE_URL` と `NEXT_PUBLIC_SUPABASE_ANON_KEY`（publishable キー）を設定してからビルドします。
- 本番のURLが決まったら、Supabase の「Authentication」→「URL Configuration」で Site URL を本番URLにし、Redirect URLs に `http://localhost:3000` も残します。

## 6. Supabase に取り込む

```bash
python -m pipeline.cli publish IT2026A
```

- `.env` に `SUPABASE_URL` と `SUPABASE_SERVICE_ROLE_KEY` が必要です。
- service_role キーは取り込み専用です。ブラウザ、Git、チャットには絶対に載せません。
- JSON Schema エラーがある問題集は取り込まれません。
- 同じ版は上書きされ、元の book.json は非公開バケット `book-json` にバックアップされます。

## 7. 問題集を改訂するとき

- **誤植の修正など同じ版のまま直す場合：** convert し直し、変わった問題だけ再照合します。
- **新しい版の場合：** `--version 2.0` を付けて convert します。学習履歴は問題IDで紐付くので、同じ番号の問題の履歴は引き継がれます。

## 8. データの置き場所とバックアップ

| データ | 場所 | Git | バックアップ |
| --- | --- | --- | --- |
| 原本PDF | `data/raw/<ID>/source.pdf` | 入れない（著作物） | 手元の別ドライブなどに保管 |
| 教材JSON・レポート・音声 | `data/books/<ID>/` | 入れない | `publish` で Supabase に保存。手元でも保管 |
| アプリに載せる教材 | `web/public/books/` | サンプルのみ | `sync-books` でいつでも作り直せる |
| 学習履歴 | 端末の localStorage と Supabase | ― | Supabase の自動バックアップ |
| APIキー | `.env`、`web/.env.local` | 入れない | パスワード管理ツール |

## 9. 定期点検

| 頻度 | 作業 |
| --- | --- |
| 変更のたび | GitHub の CI（pytest・アプリのテストとビルド・データベースの権限テスト）が緑であることを確認 |
| 問題集を追加したとき | `python -m pytest -q` と `cd web && npm test` を手元でも実行 |
| 月1回 | `npm audit` と `pip list --outdated` で脆弱性を確認。Supabase の利用量を確認 |
| 半年に1回 | 使っていない APIキーを無効化し、必要なものは作り直す |

通しテスト（`tests/test_e2e.py`）は、実際のコマンドを順に実行し、次の流れを一時フォルダの中で確かめます。

- PDF → JSON → 検証 → 人の確認 → 音声 → アプリ用データ
- 1000問の変換
- 件数違いの検出
- エラー時のメッセージ

## 10. 困ったとき

| 症状 | 原因 | 対処 |
| --- | --- | --- |
| `エラー: …PDFを開けません` | 壊れたPDF、パスワード付き | PDFを開き直して保存し直す。パスワードは解除する |
| スキャンPDFで問題が0問 | Tesseract の日本語データが無い | README の手順で `tesseract-ocr-jpn` を入れる。`TESSDATA_PREFIX` を確認 |
| 問題数が大きく足りない | 未対応の問題番号の書式（`【1】` など） | `pipeline/parse.py` の `Q_START` に追加するか `--ai` |
| `audio` で `ffmpeg が見つかりません` | ffmpeg 未インストール | README の手順で入れる |
| `VOICEVOXに接続できません` | VOICEVOX が起動していない | アプリを起動するか Docker で起動する |
| `publish` で HTTP 401/403 | キーの間違い | `.env` の service_role キーを確認する（publishable キーでは取り込めない） |
| SQL Editor で `relation "books" already exists` | マイグレーションを2回実行した | 問題なし。1回目で作成済み |
| ログインメールのリンクが localhost に飛ぶ | Site URL が開発用のまま | Supabase の URL Configuration を本番URLにする |
| 他の端末に履歴が出ない | 未ログイン、または通信失敗 | 問題集ページの同期表示を確認。履歴は端末に残り、次回送信される |
| 「まだクラウドに登録されていない」と出る | その問題集を Supabase に取り込んでいない | `python -m pipeline.cli publish <ID>` を実行する。履歴は端末に残り、取り込み後に送信される |
| ログインメールが届かない、`email rate limit exceeded` | Supabase 標準のメール送信は1時間に2通まで | 1時間待つ。人数が増えたら Authentication の SMTP 設定で独自のメールサービスを使う |
| アプリに問題集が出ない | sync-books の実行忘れ | `npm run sync-books` してからビルドし直す |

## セキュリティの約束

- APIキーは `.env` だけに置きます。`.env` は Git に入りません。
- ブラウザに渡すのは Supabase の publishable（anon）キーだけです。データベースの行単位の権限設定（RLS）により、各利用者は自分の履歴しか読めません。
- 個人情報はログイン用のメールアドレスだけを扱い、ほかは集めません。
- 原本PDFは公開しません。アプリに載るのは確認済みの教材JSON・図・音声だけです。
