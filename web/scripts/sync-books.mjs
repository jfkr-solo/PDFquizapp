// パイプラインの出力（../data/books/<id>/book.json と images/、audio/）をアプリの public/books/ にコピーし、
// 一覧 public/books/index.json を作り直す。  使い方: npm run sync-books
import fs from "node:fs";
import path from "node:path";

const root = path.resolve(import.meta.dirname, "..");
// 通しテストでは PDFQUIZ_DATA / PDFQUIZ_PUBLIC_BOOKS で入出力先を差し替える
const src = process.env.PDFQUIZ_DATA ? path.join(process.env.PDFQUIZ_DATA, "books") : path.resolve(root, "..", "data", "books");
const dst = process.env.PDFQUIZ_PUBLIC_BOOKS || path.join(root, "public", "books");
fs.mkdirSync(dst, { recursive: true });

let copied = 0;
if (fs.existsSync(src)) {
  for (const id of fs.readdirSync(src)) {
    const book = path.join(src, id, "book.json");
    if (!fs.existsSync(book)) continue;
    const out = path.join(dst, id);
    fs.rmSync(out, { recursive: true, force: true });
    fs.mkdirSync(out, { recursive: true });
    fs.copyFileSync(book, path.join(out, "book.json"));
    const img = path.join(src, id, "images");
    if (fs.existsSync(img)) fs.cpSync(img, path.join(out, "images"), { recursive: true });
    const audio = path.join(src, id, "audio"); // STEP 9 の音声（キャッシュ .cache は除く）
    if (fs.existsSync(audio)) fs.cpSync(audio, path.join(out, "audio"), { recursive: true, filter: (f) => !f.includes(`${path.sep}.cache`) });
    copied++;
  }
}

const READY = ["verified", "auto_ok"];
const index = [];
for (const id of fs.readdirSync(dst).sort()) {
  const p = path.join(dst, id, "book.json");
  if (!fs.existsSync(p)) continue;
  try {
    const b = JSON.parse(fs.readFileSync(p, "utf8"));
    const allowed = b.exam_policy?.allowed_statuses ?? READY;
    index.push({
      book_id: b.book_id,
      book_title: b.book_title,
      version: b.version,
      question_count: b.questions.length,
      ready_count: b.questions.filter((q) => allowed.includes(q.validation_status)).length,
    });
  } catch (e) {
    console.error(`読み込み失敗: ${p}: ${e.message}`);
    process.exitCode = 1;
  }
}
fs.writeFileSync(path.join(dst, "index.json"), JSON.stringify(index, null, 1));
console.log(`コピー ${copied}冊 / 一覧 ${index.length}冊: ${index.map((b) => `${b.book_id}(${b.ready_count}/${b.question_count}問)`).join(", ")}`);
