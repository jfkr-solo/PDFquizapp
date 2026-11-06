# PDF問題集 → 教材JSON 変換パイプライン（STEP 2〜6）

PDF問題集から「問題・選択肢・正解・解説・図・原本ページ」を取り出し、JSON Schemaと10項目のチェックで検証した教材JSONを作ります。設計の全体像は設計書（Claude Doc「PDF問題集クイズ学習プラットフォーム 設計書」）を参照してください。

## セットアップ

```bash
python -m venv .venv && source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt
# スキャンPDFを扱う場合のみ（OCR）
#   macOS:  brew install tesseract tesseract-lang
#   Ubuntu: sudo apt install tesseract-ocr tesseract-ocr-jpn
#   Windows: https://github.com/UB-Mannheim/tesseract/wiki から日本語データ付きでインストール
cp .env.example .env   # AI補助を使う場合のみ ANTHROPIC_API_KEY を設定
```

## 使い方

```bash
# 1. サンプルPDFを作る（テキスト版とスキャン版）
python -m tests.make_sample_pdf data/raw/SAMPLE01

# 2. 変換（抽出 → 構造化 → JSON生成 → 検証）
python -m pipeline.cli convert data/raw/SAMPLE01/sample_text.pdf --book-id SAMPLE01 --title "IT基礎問題集（サンプル）" --expected 6
```

期待される出力:

```text
[1/4] PDF抽出 ...
      ページ数: 3 / 抽出方法: {'text': 3} / 画像: 1件 / 警告: 0件
[2/4] 問題・解答の構造化 ...
      問題 6問 / 解答 6件 / 全体の指摘 0件
[3/4] 教材JSON生成 ...
      data/books/SAMPLE01/book.json（6問）
[4/4] 検証 ...
      自動検証OK 6 / 確認済み 0 / 要確認 0 / 除外 0
      JSON Schema: OK
      レポート: data/books/SAMPLE01/validation_report.md
```

スキャン版では、OCRで読んだ問題はすべて「要確認」になり、解答の読み取り失敗や図の切り出しがレポートに出ます。

```bash
python -m pipeline.cli convert data/raw/SAMPLE01/sample_scan.pdf --book-id SAMPLE01S --title "スキャン版" --expected 6
# → 自動検証OK 0 / 要確認 6、ANSWER_COUNT_MISMATCH（問題6問に対して解答5件）など
```

人が原本と照合したら、確認済みにします（内容が後で変わると自動で要確認に戻ります）。

```bash
python -m pipeline.cli verify SAMPLE01S SAMPLE01S-Q0002 --note "原本p.1と照合"
python -m pipeline.cli reject SAMPLE01S SAMPLE01S-Q0004 --note "解答が判読不能"
python -m pipeline.cli validate SAMPLE01S     # 再検証だけ行う
```

ルールで問題を見つけられないページがある本は `--ai` を付けると、そのページだけ生成AIで行を整形します（正解はAIに決めさせず、原文に無い文章は捨て、該当問題は必ず要確認）。

## テスト

```bash
python -m pytest -q
# 11 passed
```

テストは、テキストPDF・スキャンPDF（Tesseractが無ければ自動スキップ）・意図的に壊したデータの検出・確認済みの巻き戻り・章ごとの番号振り直し・1行の解答一覧・AI補助のガードを確認します。

## 各工程の入出力

| 工程 | モジュール | 入力 | 出力 |
| --- | --- | --- | --- |
| STEP 2 抽出 | `pipeline/extract.py` | 原本PDF | `pages.json`、`images/*.png` |
| STEP 3 構造化 | `pipeline/parse.py`（＋`ai_assist.py`） | `pages.json` | `parsed.json` |
| STEP 4 JSON生成 | `pipeline/build_json.py` | `parsed.json`、原本PDF | `book.json` |
| STEP 5 検証 | `pipeline/validate.py`、`schema/question_book.schema.json` | `book.json`、`pages.json` | `book.json`（状態更新）、`validation_report.md/.json` |

原本は `data/raw/<book_id>/source.pdf`、加工データは `data/books/<book_id>/` に分かれます。

## 問題の状態

| 状態 | 意味 | 模擬試験に出るか |
| --- | --- | --- |
| `verified` | 人が原本と照合済み | 出る |
| `auto_ok` | 自動検証で error / review の指摘なし | 出る（`exam_policy` で変更可） |
| `pending` | 要確認（解答なし、OCR由来、AI補助、図の欠落など） | 出ない |
| `rejected` | 人が除外 | 出ない |

## 対応している書式

- 問題番号: `問1` `問題1` `Q1` `第1問`（全角数字可）
- 選択肢: `ア〜ク` `A〜H` `①〜⑧` `(1)〜(8)`、1行に並んだ選択肢、複数行の選択肢
- 解答: 巻末の「解答」「解答・解説」「解答一覧」見出し以降、または各問題直後の `正解：イ`／`解説：…`
- 問題形式: 単一選択、複数選択（正解が2つ以上）、○×、数値（単位付き）
- 章: `第1章 ネットワーク` → chapter「第1章」、category「ネットワーク」

これ以外の書式（`【1】` や `No.1` など）は `parse.py` の `Q_START` に追加するか、`--ai` で補助します。

## 既知の制約

- 2段組は簡易判定です。複雑なレイアウト（段の途中に図、3段組）は要確認になります。
- スキャンPDFの図は画像として取り出せないため、問題の範囲をページから切り出して添付し、要確認にします。
- OCRの誤認識（例「層」→「必」）は自動では直しません。OCR由来の問題は必ず人の確認を通します。

## STEP 7：クイズアプリ（`web/`）

Next.js（静的書き出し）のクイズアプリです。`book.json` を直接読み込み、学習履歴はブラウザ（localStorage）に保存します。STEP 8 で保存先をSupabaseに差し替えます（`web/lib/storage.ts` の `HistoryStore`）。

```bash
cd web
npm install
npm run sync-books   # ../data/books/<id>/ の book.json と画像を public/books/ にコピーし、一覧を作る
npm run dev          # http://localhost:3000
npm test             # 出題・採点ロジックの単体テスト（9件）
npm run build        # out/ に静的ファイルを書き出す（Vercel等にそのまま置ける）
```

| 画面 | 内容 |
| --- | --- |
| 問題集一覧 `/` | 問題集ごとの出題可能数・要確認数・学習進捗 |
| 問題集 `/book/?id=…` | 章・分野・難易度の絞り込み、4つの学習モード、正答率（全体・章別・分野別・難易度別）、苦手分野ランキング、前回間違えた問題、途中からの再開 |
| 出題 `/play/?…` | 4択・○×・複数選択・数値入力。通常学習は1問ごとに正解と解説、模擬試験は最後に採点 |

- 模擬試験・弱点克服・復習は `verified` と `auto_ok` の問題だけを出します。通常学習でのみ「要確認の問題も含める」を選べます（バッジで明示）。
- 1問回答するたびに進捗を保存するので、途中で閉じても「続きから」で再開できます。
- `web/public/books/` には動作確認用のサンプル2冊（テキスト版・スキャン版）を同梱しています。実際の問題集は著作権の都合でコミットしないでください。

## STEP 8：Supabase連携

学習履歴をSupabaseに保存し、端末間で共有します。設定手順は [supabase/README.md](supabase/README.md) を参照してください。

- `supabase/migrations/`：テーブル・RLS（本人の履歴だけ読める）・集計トリガー・正答率ビュー
- `python -m pipeline.cli publish <book_id>`：検証済みの book.json を取り込み、元JSONを非公開バケットにバックアップ
- アプリ：`NEXT_PUBLIC_SUPABASE_URL` と `NEXT_PUBLIC_SUPABASE_ANON_KEY` を設定すると、メールのリンクでログインできるようになります。履歴はまず端末に保存し、ログイン中は自動で同期します（未設定ならこれまでどおり端末内のみ）
