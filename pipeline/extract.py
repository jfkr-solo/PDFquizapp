"""STEP 2: PDFをページ単位で読み込み、行テキスト・座標・画像を pages.json に保存する。

入力 : PDFファイル
出力 : <out_dir>/pages.json, <out_dir>/images/*.png

- テキスト型ページは PyMuPDF でそのまま抽出する。
- 文字数が閾値未満のページはスキャンと判定し、Tesseract OCR（PyMuPDF経由）を使う。
- 2段組はブロックの左右位置から段を判定し、左段→右段の順に並べる。
- 画像は座標付きで保存し、後工程で問題に紐付ける。
- 黒地に白抜き文字の見出し（「第1問」のラベルなど）は通常のOCRでは読めないため、
  白黒を反転して切り出し、別に読み取る（_inverted_labels）。
"""
from __future__ import annotations

import hashlib
import re
import json
import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, asdict, field
from pathlib import Path

import pymupdf  # PyMuPDF


class ExtractError(Exception):
    pass


@dataclass
class Line:
    text: str
    x0: float
    y0: float
    x1: float
    y1: float


@dataclass
class ImageRef:
    path: str
    x0: float
    y0: float
    x1: float
    y1: float


@dataclass
class PageResult:
    page: int                     # 1始まり（原本のページ番号）
    method: str                   # text | ocr | ocr_unavailable | empty
    width: float
    height: float
    lines: list[Line] = field(default_factory=list)
    images: list[ImageRef] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def text(self) -> str:
        return "\n".join(l.text for l in self.lines)


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def find_tessdata() -> str | None:
    env = os.environ.get("TESSDATA_PREFIX")
    if env and Path(env).is_dir():
        return env
    for cand in ("/usr/share/tesseract-ocr/5/tessdata", "/usr/share/tesseract-ocr/4.00/tessdata",
                 "/opt/homebrew/share/tessdata", "/usr/local/share/tessdata",
                 r"C:\Program Files\Tesseract-OCR\tessdata"):
        if Path(cand).is_dir():
            return cand
    return None


def _order_blocks(blocks: list[dict], page_width: float) -> list[dict]:
    """2段組を考慮してテキストブロックを読み順に並べる。"""
    mid = page_width / 2
    left = [b for b in blocks if b["bbox"][2] <= mid + 10]
    right = [b for b in blocks if b["bbox"][0] >= mid - 10]
    spanning = [b for b in blocks if b not in left and b not in right]
    two_column = len(right) >= 3 and len(left) >= 3 and len(spanning) <= max(2, len(blocks) // 5)
    if not two_column:
        return sorted(blocks, key=lambda b: (round(b["bbox"][1], 1), b["bbox"][0]))
    # 段組の上にある全幅ブロック（見出し）→ 左段 → 右段 → 段組の下の全幅ブロック
    col_top = min(b["bbox"][1] for b in left + right)
    above = [b for b in spanning if b["bbox"][1] < col_top]
    below = [b for b in spanning if b["bbox"][1] >= col_top]
    key = lambda b: b["bbox"][1]
    return sorted(above, key=key) + sorted(left, key=key) + sorted(right, key=key) + sorted(below, key=key)


def _lines_from_dict(d: dict, page_width: float) -> list[Line]:
    text_blocks = [b for b in d.get("blocks", []) if b.get("type") == 0]
    out: list[Line] = []
    for b in _order_blocks(text_blocks, page_width):
        for ln in b.get("lines", []):
            txt = "".join(s.get("text", "") for s in ln.get("spans", [])).strip()
            if txt:
                x0, y0, x1, y1 = ln["bbox"]
                out.append(Line(txt, round(x0, 1), round(y0, 1), round(x1, 1), round(y1, 1)))
    return out


_CJK = r"\u3000-\u30ff\u3400-\u9fff\uff00-\uffef"
_CJK_SPACE = re.compile(rf"(?<=[{_CJK}])\s+(?=[{_CJK}A-Za-z0-9])|(?<=[A-Za-z0-9])\s+(?=[{_CJK}])")


def _dark_boxes(gray, *, block: int = 10, dark: int = 110, solid: float = 0.55,
                min_w: int = 16, min_h: int = 4, fill: float = 0.7, margin: float = 0.05) -> list[tuple[int, int, int, int]]:
    """黒く塗りつぶされた四角形（白抜き文字の地）を探し、(x0, y0, x1, y1) のピクセル座標で返す。

    10px角のブロック単位で「ほぼ黒」を判定し、細い罫線は収縮→膨張で取り除いてから塊を拾う。
    ページ端（左右5%）にかかる章見出しのツメ（幅が狭い）は、問題の途中で章が切り替わったと誤認しないよう除く。
    """
    import numpy as np
    from collections import deque

    h, w = gray.shape
    H, W = h // block, w // block
    g = (gray[:H * block, :W * block] < dark).reshape(H, block, W, block).mean(axis=(1, 3)) > solid

    def morph(m, r, op):
        p = np.pad(m, r, constant_values=False)
        acc = None
        for dy in range(2 * r + 1):
            for dx in range(2 * r + 1):
                v = p[dy:dy + m.shape[0], dx:dx + m.shape[1]]
                acc = v if acc is None else op(acc, v)
        return acc

    g = morph(morph(g, 2, np.logical_and), 2, np.logical_or)
    seen = np.zeros_like(g)
    boxes = []
    for y, x in zip(*np.nonzero(g)):
        if seen[y, x]:
            continue
        q = deque([(y, x)])
        seen[y, x] = True
        cells = []
        while q:
            cy, cx = q.popleft()
            cells.append((cy, cx))
            for ny, nx in ((cy + 1, cx), (cy - 1, cx), (cy, cx + 1), (cy, cx - 1)):
                if 0 <= ny < H and 0 <= nx < W and g[ny, nx] and not seen[ny, nx]:
                    seen[ny, nx] = True
                    q.append((ny, nx))
        ys = [c[0] for c in cells]
        xs = [c[1] for c in cells]
        bh, bw = max(ys) - min(ys) + 1, max(xs) - min(xs) + 1
        x0, x1 = min(xs) * block, (max(xs) + 1) * block
        if bw >= min_w and bh >= min_h and len(cells) / (bw * bh) >= fill and x0 >= w * margin and x1 <= w * (1 - margin):
            boxes.append((x0, min(ys) * block, x1, (max(ys) + 1) * block))
    return boxes


Box = tuple[float, float, float, float]


def _inverted_labels(page: "pymupdf.Page", ocr_lang: str, tessdata: str, dpi: int = 300) -> list[tuple[Line, Box]]:
    """白抜き文字を反転してTesseractで読み、(読み取った行, 黒地の範囲) をページ座標（pt）で返す。"""
    import numpy as np

    pix = page.get_pixmap(dpi=dpi, colorspace=pymupdf.csGRAY)
    gray = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.stride)[:, :pix.width]
    scale = 72 / dpi
    out: list[tuple[Line, Box]] = []
    env = {**os.environ, "TESSDATA_PREFIX": tessdata}
    with tempfile.TemporaryDirectory() as td:
        for k, (x0, y0, x1, y1) in enumerate(_dark_boxes(gray)):
            crop = np.ascontiguousarray(255 - gray[y0:y1, x0:x1])
            img = Path(td) / f"box{k}.png"
            pymupdf.Pixmap(pymupdf.csGRAY, crop.shape[1], crop.shape[0], crop.tobytes(), False).save(img)
            r = subprocess.run(["tesseract", str(img), "-", "-l", ocr_lang, "--psm", "6", "tsv"],
                               capture_output=True, text=True, env=env, timeout=60)
            words = []
            for row in r.stdout.splitlines()[1:]:
                c = row.split("\t")
                if len(c) == 12 and c[11].strip() and float(c[10]) >= 0:
                    words.append((int(c[6]), int(c[7]), int(c[8]), int(c[9]), c[11].strip()))
            if not words:
                continue
            text = _CJK_SPACE.sub("", " ".join(wd[4] for wd in words)).replace(" ", "")
            wx0 = min(wd[0] for wd in words) + x0
            wy0 = min(wd[1] for wd in words) + y0
            wx1 = max(wd[0] + wd[2] for wd in words) + x0
            wy1 = max(wd[1] + wd[3] for wd in words) + y0
            line = Line(text, round(wx0 * scale, 1), round(wy0 * scale, 1), round(wx1 * scale, 1), round(wy1 * scale, 1))
            out.append((line, (x0 * scale, y0 * scale, x1 * scale, y1 * scale)))
    return out


def _apply_labels(d: dict, labels: list[tuple[Line, Box]]) -> list[Line]:
    """白抜き部分の読み違い（OCRのゴミ）を get_text("dict") の結果から除き、読み直したラベルの行を返す。

    ラベルは黒地の上端に置く。こうすると同じ黒地の横にある問題文より必ず先に並び、
    問題文の1行目が前の問題に混ざらない。
    """
    def inside(bb, box) -> bool:
        cx, cy = (bb[0] + bb[2]) / 2, (bb[1] + bb[3]) / 2
        return box[0] <= cx <= box[2] and box[1] <= cy <= box[3]
    boxes = [box for _, box in labels]
    for b in d.get("blocks", []):
        for ln in b.get("lines", []):
            ln["spans"] = [sp for sp in ln.get("spans", []) if not any(inside(sp["bbox"], bx) for bx in boxes)]
    return [Line(lb.text, lb.x0, round(box[1], 1), lb.x1, round(box[1] + 1, 1)) for lb, box in labels]


def _merge_rows(lines: list[Line], page_width: float) -> list[Line]:
    """OCRで細切れになった同じ行の断片を1行にまとめる（段組は左右で分けて処理）。"""
    if not lines:
        return lines
    mid = page_width / 2
    right = [l for l in lines if l.x0 >= mid - 10]
    left = [l for l in lines if l.x0 < mid - 10]
    two_column = len(right) >= 5 and len(left) >= 5 and all(l.x1 <= mid + 30 for l in left)
    groups = [left, right] if two_column else [lines]
    out: list[Line] = []
    for group in groups:
        rows: list[list[Line]] = []
        for ln in sorted(group, key=lambda l: (l.y0 + l.y1) / 2):
            cy = (ln.y0 + ln.y1) / 2
            if rows:
                last = rows[-1]
                ry0, ry1 = min(l.y0 for l in last), max(l.y1 for l in last)
                if ry0 <= cy <= ry1:
                    last.append(ln)
                    continue
            rows.append([ln])
        for row in rows:
            row.sort(key=lambda l: l.x0)
            text = " ".join(l.text for l in row)
            text = _CJK_SPACE.sub("", text)
            out.append(Line(text, row[0].x0, min(l.y0 for l in row), max(l.x1 for l in row), max(l.y1 for l in row)))
    return out


def _save_images(doc: pymupdf.Document, page: pymupdf.Page, page_no: int, img_dir: Path,
                 min_size: int) -> list[ImageRef]:
    refs: list[ImageRef] = []
    for idx, info in enumerate(page.get_images(full=True), start=1):
        xref = info[0]
        rects = page.get_image_rects(xref)
        if not rects:
            continue
        r = rects[0]
        if r.width < min_size or r.height < min_size:
            continue  # 罫線・ロゴなど小さな画像は除外
        if r.width * r.height > 0.8 * page.rect.width * page.rect.height:
            continue  # スキャン原稿のページ全体画像は図ではない
        pix = pymupdf.Pixmap(doc, xref)
        if pix.n - pix.alpha >= 4:  # CMYK → RGB
            pix = pymupdf.Pixmap(pymupdf.csRGB, pix)
        name = f"p{page_no:03d}_{idx:02d}.png"
        pix.save(img_dir / name)
        refs.append(ImageRef(f"images/{name}", round(r.x0, 1), round(r.y0, 1), round(r.x1, 1), round(r.y1, 1)))
    return refs


def extract_pdf(pdf_path: str | Path, out_dir: str | Path, *, ocr_lang: str = "jpn",
                min_chars: int = 20, ocr_dpi: int = 300, min_image_size: int = 40,
                force_ocr: bool = False) -> dict:
    pdf_path, out_dir = Path(pdf_path), Path(out_dir)
    if not pdf_path.is_file():
        raise ExtractError(f"PDFが見つかりません: {pdf_path}")
    try:
        doc = pymupdf.open(pdf_path)
    except Exception as e:  # 壊れたPDFなど
        raise ExtractError(f"PDFを開けません: {pdf_path}: {e}") from e
    if doc.needs_pass:
        raise ExtractError("パスワード付きPDFには対応していません。解除してから実行してください。")

    img_dir = out_dir / "images"
    if img_dir.exists():
        shutil.rmtree(img_dir)
    img_dir.mkdir(parents=True, exist_ok=True)
    tessdata = find_tessdata()

    pages: list[PageResult] = []
    for i, page in enumerate(doc, start=1):
        w, h = page.rect.width, page.rect.height
        res = PageResult(page=i, method="text", width=round(w, 1), height=round(h, 1))
        try:
            d = page.get_text("dict")
            res.lines = _lines_from_dict(d, w)
            if force_ocr or sum(len(l.text) for l in res.lines) < min_chars:
                if tessdata is None:
                    res.method = "ocr_unavailable"
                    res.warnings.append("テキストが少ないためOCRが必要ですが、Tesseractが見つかりません")
                else:
                    tp = page.get_textpage_ocr(language=ocr_lang, dpi=ocr_dpi, full=True, tessdata=tessdata)
                    d = page.get_text("dict", textpage=tp)
                    labels: list[Line] = []
                    try:
                        labels = _apply_labels(d, _inverted_labels(page, ocr_lang, tessdata, ocr_dpi))
                    except Exception as e:  # 白抜き文字の読み取りに失敗しても本文のOCR結果は使う
                        res.warnings.append(f"白抜き文字を読み取れませんでした: {type(e).__name__}: {e}")
                    res.lines = _merge_rows(_lines_from_dict(d, w) + labels, w)
                    res.method = "ocr"
            if not res.lines:
                res.method = "empty" if res.method == "text" else res.method
            res.images = _save_images(doc, page, i, img_dir, min_image_size)
        except Exception as e:  # 1ページの失敗で全体を止めない
            res.warnings.append(f"ページ処理エラー: {type(e).__name__}: {e}")
        pages.append(res)

    result = {
        "source_pdf": {"file": pdf_path.name, "sha256": sha256_of(pdf_path), "pages": len(doc)},
        "pages": [
            {**{k: v for k, v in asdict(p).items()}, "char_count": sum(len(l.text) for l in p.lines)}
            for p in pages
        ],
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "pages.json").write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    return result


def summarize(result: dict) -> str:
    methods: dict[str, int] = {}
    for p in result["pages"]:
        methods[p["method"]] = methods.get(p["method"], 0) + 1
    n_img = sum(len(p["images"]) for p in result["pages"])
    n_warn = sum(len(p["warnings"]) for p in result["pages"])
    return (f"ページ数: {result['source_pdf']['pages']} / 抽出方法: {methods} / "
            f"画像: {n_img}件 / 警告: {n_warn}件")
