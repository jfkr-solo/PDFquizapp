"""別紙の正解一覧（解答キー）を読み込む。

問題集の解答ページがOCRで読めないとき、人が用意した正解一覧から正解を取る。
形式は1行または連続した「第1章 第1問 ②」の並び（PDF・テキストどちらでも可）。章が無い本は「第1問 ②」でもよい。

  python -m pipeline.cli convert 問題集.pdf --book-id IT01 --title "…" \
      --chapter-pages 1,29,41 --answer-key 正解一覧.pdf
"""
from __future__ import annotations

import re
from pathlib import Path

from .parse import ANS_MARK, norm

_ENTRY = re.compile(rf"(?:第\s*(\d+)\s*章\s*)?第\s*(\d+)\s*問\s*({ANS_MARK}(?:\s*[、,・]\s*{ANS_MARK})*)")


class AnswerKeyError(Exception):
    pass


def parse_answer_key(text: str) -> dict[tuple[str, int], list[str]]:
    """テキスト → {(章, 問番号): [正解の記号…]}。章が書かれていない行は直前の章を引き継ぐ。"""
    flat = re.sub(r"\s+", " ", norm(text))
    out: dict[tuple[str, int], list[str]] = {}
    chapter = ""
    for m in _ENTRY.finditer(flat):
        if m.group(1):
            chapter = f"第{int(m.group(1))}章"
        key = (chapter, int(m.group(2)))
        toks = re.findall(ANS_MARK, m.group(3))
        if key in out and out[key] != toks:
            raise AnswerKeyError(f"正解一覧で {chapter}第{key[1]}問 が2回、違う正解で出てきます（{out[key]} と {toks}）")
        out[key] = toks
    if not out:
        raise AnswerKeyError("正解一覧から「第1問 ②」のような行を読み取れませんでした")
    return out


def load_answer_key(path: str | Path) -> dict[tuple[str, int], list[str]]:
    path = Path(path)
    if not path.is_file():
        raise AnswerKeyError(f"正解一覧が見つかりません: {path}")
    if path.suffix.lower() == ".pdf":
        import pymupdf
        with pymupdf.open(path) as d:
            text = "\n".join(p.get_text() for p in d)
        if not text.strip():
            raise AnswerKeyError("正解一覧のPDFに文字がありません（スキャンの場合は文字入りのPDFかテキストで用意してください）")
    else:
        text = path.read_text(encoding="utf-8")
    return parse_answer_key(text)
