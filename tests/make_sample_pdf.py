"""動作確認用のサンプル問題集PDFを生成する。

  python -m tests.make_sample_pdf data/raw/SAMPLE01

出力:
  sample_text.pdf  … テキストをコピーできるPDF（3ページ・6問・図1点）
  sample_scan.pdf  … 同じ内容をラスタ画像にしたスキャン風PDF（OCR確認用）
"""
from __future__ import annotations

import sys
from pathlib import Path

import pymupdf

FONT = "japan"  # PyMuPDF内蔵の日本語フォント

PAGE1 = [
    ("IT基礎問題集（サンプル）", 16),
    ("第1章 ネットワーク", 13),
    ("問1 OSI参照モデルで、IPが属する層はどれか。", 11),
    ("ア 物理層", 11), ("イ データリンク層", 11), ("ウ ネットワーク層", 11), ("エ トランスポート層", 11),
    ("", 11),
    ("問2 次のうち、プライベートIPアドレスをすべて選べ。", 11),
    ("ア 10.0.0.1", 11), ("イ 172.16.0.1", 11), ("ウ 192.168.1.1", 11), ("エ 8.8.8.8", 11),
    ("", 11),
    ("問3 図1のネットワーク構成で、ルータは何台あるか。", 11),
]
PAGE1_AFTER_FIG = [
    ("ア 1台　イ 2台　ウ 3台　エ 4台", 11),
]
PAGE2 = [
    ("第2章 セキュリティ", 13),
    ("問4 公開鍵暗号方式では、暗号化と復号に同じ鍵を使う。○か×で答えよ。", 11),
    ("", 11),
    ("問5 100Mbpsの回線で50MBのファイルを転送する時間は何秒か。", 11),
    ("伝送効率は100%とする。", 11),
    ("", 11),
    ("問6 パスワードの管理方法として最も適切なものはどれか。", 11),
    ("ア 付箋に書いてモニターに貼る", 11), ("イ 全サービスで同じパスワードを使う", 11),
    ("ウ パスワードマネージャーを使う", 11), ("エ 毎月、誕生日に変更する", 11),
]
PAGE3 = [
    ("解答・解説", 14),
    ("問1 ウ", 11),
    ("解説：IPはネットワーク層（第3層）のプロトコルである。", 11),
    ("問2 ア、イ、ウ", 11),
    ("解説：10.0.0.0/8、172.16.0.0/12、192.168.0.0/16が該当する。", 11),
    ("問3 イ", 11),
    ("解説：図1にはルータが2台ある。", 11),
    ("問4 ×", 11),
    ("解説：公開鍵暗号方式では、暗号化と復号に異なる鍵を使う。", 11),
    ("問5 4 秒", 11),
    ("解説：50MB＝400Mbitなので、400÷100＝4秒。", 11),
    ("問6 ウ", 11),
]


def _figure_png() -> bytes:
    """ルータ2台・PC2台の簡単な構成図（PNG）を作る。"""
    doc = pymupdf.open()
    p = doc.new_page(width=300, height=120)
    for x, label in ((20, "PC1"), (100, "R1"), (180, "R2"), (250, "PC2")):
        p.draw_rect(pymupdf.Rect(x, 40, x + 40, 80), color=(0, 0, 0), width=1.5)
        p.insert_text((x + 8, 65), label, fontsize=11)
    for x0, x1 in ((60, 100), (140, 180), (220, 250)):
        p.draw_line((x0, 60), (x1, 60), color=(0, 0, 0), width=1.5)
    p.insert_text((110, 105), "Fig.1", fontsize=10)
    return p.get_pixmap(dpi=150).tobytes("png")


def _write_lines(page: pymupdf.Page, lines, y: float) -> float:
    for text, size in lines:
        if text:
            page.insert_text((60, y), text, fontsize=size, fontname=FONT)
        y += size * 1.9
    return y


def make_text_pdf(path: Path) -> None:
    doc = pymupdf.open()
    p1 = doc.new_page(width=595, height=842)  # A4
    y = _write_lines(p1, PAGE1, 70)
    fig_rect = pymupdf.Rect(80, y, 380, y + 120)
    p1.insert_image(fig_rect, stream=_figure_png())
    _write_lines(p1, PAGE1_AFTER_FIG, fig_rect.y1 + 22)
    _write_lines(doc.new_page(width=595, height=842), PAGE2, 70)
    _write_lines(doc.new_page(width=595, height=842), PAGE3, 70)
    doc.save(path)


def make_scan_pdf(src: Path, path: Path, dpi: int = 200) -> None:
    """テキスト層を持たない、画像だけのPDFを作る（スキャン原稿の再現）。"""
    src_doc, out = pymupdf.open(src), pymupdf.open()
    for page in src_doc:
        pix = page.get_pixmap(dpi=dpi, colorspace=pymupdf.csGRAY)
        new = out.new_page(width=page.rect.width, height=page.rect.height)
        new.insert_image(new.rect, stream=pix.tobytes("png"))
    out.save(path)


def main(out_dir: str = "data/raw/SAMPLE01") -> None:
    d = Path(out_dir)
    d.mkdir(parents=True, exist_ok=True)
    make_text_pdf(d / "sample_text.pdf")
    make_scan_pdf(d / "sample_text.pdf", d / "sample_scan.pdf")
    print(f"作成: {d / 'sample_text.pdf'}, {d / 'sample_scan.pdf'}")


if __name__ == "__main__":
    main(*sys.argv[1:])
