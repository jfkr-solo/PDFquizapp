"""STEP 3 補助: ルールで問題を見つけられなかったページだけ、生成AIで「行の整形」を行う。

AIに任せるのは「どこからどこまでが問題文・選択肢か」を 問N / ア… の形に並べ直すことだけです。
- 正解・解説はAIに渡さない（解答ページは対象外）。正解は従来どおり原本の解答ページから取る。
- AIが返した各行が原本テキストに含まれているかを照合し、含まれない行は捨てて警告にする。
- AI補助したページの問題は必ず「要確認」になる（build_json で AI_ASSISTED を付与）。

必要: pip install anthropic pydantic、環境変数 ANTHROPIC_API_KEY
"""
from __future__ import annotations

import json
import os
import re
import unicodedata
from pathlib import Path

from pydantic import BaseModel

from .parse import Q_START, parse_pages

MAX_PAGES_PER_BATCH = 5   # 1ページ10問前後として、1回あたり約50問
MIN_CHARS = 200


class AIOption(BaseModel):
    label: str
    text: str


class AIQuestion(BaseModel):
    number: int
    question: str
    options: list[AIOption]


class AIPage(BaseModel):
    page: int
    questions: list[AIQuestion]


class AIResult(BaseModel):
    pages: list[AIPage]


PROMPT = """あなたは問題集PDFのテキストを整理する担当です。以下のページテキストから、問題番号・問題文・選択肢を抜き出してください。

厳守事項:
- 文章は原文のまま一字一句写す。言い換え・要約・誤字の修正をしない。
- 正解や解説を推測して書かない（このテキストに解答は含まれていません）。
- 判読できない文字は推測せず「〓」にする。
- 選択肢が無い問題（○×・計算問題）は options を空にする。
- label は原本の記号（ア、①、A など）をそのまま使う。

<pages>
{pages}
</pages>"""


def _n(s: str) -> str:
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", s))


def pages_needing_help(pages_json: dict, parsed: dict) -> list[int]:
    ans_page = (parsed.get("answer_section") or {}).get("page") or 10 ** 9
    out = []
    for p in pages_json["pages"]:
        if p["page"] >= ans_page or p["char_count"] < MIN_CHARS:
            continue
        if not any(Q_START.match(l["text"].strip()) for l in p["lines"]):
            out.append(p["page"])
    return out


def _call_claude(client, page_texts: dict[int, str]) -> AIResult:
    body = "\n".join(f'<page number="{n}">\n{t}\n</page>' for n, t in page_texts.items())
    resp = client.messages.parse(
        model=os.environ.get("CLAUDE_MODEL", "claude-opus-5-5"),
        max_tokens=16000,
        messages=[{"role": "user", "content": PROMPT.format(pages=body)}],
        output_format=AIResult,
    )
    if getattr(resp, "stop_reason", None) == "refusal":
        raise RuntimeError("AIが処理を拒否しました")
    if getattr(resp, "stop_reason", None) == "max_tokens":
        raise RuntimeError("AIの出力が上限で途切れました（MAX_PAGES_PER_BATCH を小さくしてください）")
    return resp.parsed_output


def assist_pages(pages_json: dict, page_numbers: list[int], client=None) -> tuple[dict, list[dict]]:
    """対象ページの lines をAIで整形した行に置き換える。戻り値 (新しい pages_json, ログ)"""
    if client is None:
        import anthropic  # 遅延import：AIを使わない人は不要
        client = anthropic.Anthropic()
    by_no = {p["page"]: p for p in pages_json["pages"]}
    log: list[dict] = []
    for i in range(0, len(page_numbers), MAX_PAGES_PER_BATCH):
        batch = page_numbers[i:i + MAX_PAGES_PER_BATCH]
        texts = {n: "\n".join(l["text"] for l in by_no[n]["lines"]) for n in batch}
        try:
            result = _call_claude(client, texts)
        except Exception as e:  # API障害でも全体は止めず、そのページはルール結果のまま
            log.append({"pages": batch, "error": f"{type(e).__name__}: {e}"})
            continue
        for ap in result.pages:
            if ap.page not in by_no:
                continue
            src = _n(texts.get(ap.page, ""))
            new_lines, dropped = [], 0
            y = 10.0

            def add(text: str, check: str) -> None:
                nonlocal y, dropped
                if check and _n(check) not in src:  # 原文に無い文章は採用しない
                    dropped += 1
                    return
                new_lines.append({"text": text, "x0": 0, "y0": y, "x1": 0, "y1": y + 10})
                y += 12

            for q in ap.questions:
                add(f"問{q.number} {q.question}", q.question)
                for o in q.options:
                    add(f"{o.label} {o.text}", o.text)
            page = by_no[ap.page]
            page["lines"] = new_lines
            page["method"] = "ai_assisted"
            if dropped:
                page["warnings"].append(f"AIの出力のうち原文と一致しない{dropped}行を除外しました")
            log.append({"page": ap.page, "questions": len(ap.questions), "dropped_lines": dropped})
    return pages_json, log


def assist_parsed(pages_path: str | Path, parsed_path: str | Path, client=None) -> dict:
    pages_path, parsed_path = Path(pages_path), Path(parsed_path)
    pages_json = json.loads(pages_path.read_text(encoding="utf-8"))
    parsed = json.loads(parsed_path.read_text(encoding="utf-8"))
    targets = pages_needing_help(pages_json, parsed)
    if not targets:
        print("      AI補助: 対象ページなし（すべてルールで処理できました）")
        return parsed
    print(f"      AI補助: {len(targets)}ページを処理します {targets}")
    pages_json, log = assist_pages(pages_json, targets, client)
    pages_path.with_name("ai_assist_log.json").write_text(json.dumps(log, ensure_ascii=False, indent=1), encoding="utf-8")
    pages_path.write_text(json.dumps(pages_json, ensure_ascii=False, indent=1), encoding="utf-8")
    parsed = parse_pages(pages_json)
    parsed_path.write_text(json.dumps(parsed, ensure_ascii=False, indent=1), encoding="utf-8")
    return parsed
