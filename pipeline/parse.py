"""STEP 3: pages.json から問題・選択肢・解答・解説をルールベースで抽出し、問題番号で紐付ける。

入力 : pages.json（STEP 2 の出力）
出力 : parsed.json（問題ごとの中間データ＋紐付けの問題点）

方針
- 正解は原本の解答ページ（または各問題直後の「正解：」行）からのみ取る。推測はしない。
- 読めない・紐付かないものは捨てずに issues に記録し、後工程で「要確認」にする。
- 問題番号が章ごとに 1 から振り直される本にも対応するため、「n 回目に出てきた問 k」同士を紐付ける。
"""
from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field, asdict
from pathlib import Path

# ---------- 正規化 ----------
_Z2H = str.maketrans("０１２３４５６７８９ＡＢＣＤＥＦＧＨＩＪＫＬＭＮＯＰＱＲＳＴＵＶＷＸＹＺａｂｃｄｅｆｇｈｉｊｋｌｍｎｏｐｑｒｓｔｕｖｗｘｙｚ（）．：",
                     "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz().:")


def norm(s: str) -> str:
    """全角英数字を半角にし、前後の空白を除く（記号の意味は変えない）。"""
    return s.translate(_Z2H).strip()


# ---------- パターン ----------
Q_START = re.compile(r"^(?:(?:問題?|Q)\s*(\d+)|第\s*(\d+)\s*問)\s*[.:、)]?\s*(.*)$")
Q_ANY = re.compile(r"(?:問題?|Q)\s*(\d+)|第\s*(\d+)\s*問")
CHAPTER = re.compile(r"^第\s*(\d+|[一二三四五六七八九十]+)\s*章\s*(.*)$")
ANSWER_CHAPTER = re.compile(r"第\s*(\d+)\s*章\s*の?\s*解[答合]")  # 「《第1章の解答・解説》」（OCRの前後のゴミは許す）
ANSWER_HEADER = re.compile(r"^(解答(・?解説|と解説|一覧|編)?|正解(一覧)?|解答解説)$")
INLINE_ANSWER = re.compile(r"^(?:正解|答え|解答)\s*[:]\s*(.+)$")
EXPLANATION = re.compile(r"^解説\s*[:]?\s*(.*)$")
OCR_LEAD_JUNK = re.compile(r"^[-ー_|'\"“”‘’:;.,\s]+(?=第\s*\d+\s*問)")  # OCRで問題番号の前に付く汚れ
OCR_DIGIT_OPTION = re.compile(r"^\(?([1-8])(?:\)|\s|(?=[^\d.,年月日%:]))")  # 丸数字①を「1」「(1)」と読み違えたもの
PAGE_NUMBER = re.compile(r"^[-－—]?\s*\d{1,4}\s*[-－—]?$")

# 選択肢の記号ファミリー（順番＝A,B,C…への対応）
FAMILIES = {
    "kana": list("アイウエオカキク"),
    "latin": list("ABCDEFGH"),
    "circled": list("①②③④⑤⑥⑦⑧"),
    "paren": [f"({i})" for i in range(1, 9)],
}
OCR_CONFUSION = {"工": "エ", "力": "カ", "才": "オ"}  # OCRでよく取り違える文字
SEP = r"[\s　.、:)]"
TF_TRUE, TF_FALSE = set("○〇oO"), set("×✕xX")
TF_HINT = re.compile(r"○か×|○×|正誤|正しければ|正しいか誤りか")

ANS_MARK = r"(?:[アイウエオカキク工力才A-H①-⑧○〇×✕]|\(\d\))"
ANS_TOKENS = re.compile(rf"^({ANS_MARK}(?:\s*[、,・\s]\s*{ANS_MARK})*)(?=$|[\s　]|解説|[。.])")
ANS_NUMERIC = re.compile(r"^([-+]?\d+(?:\.\d+)?)\s*([^\s、。]{0,8})")


@dataclass
class Option:
    id: str      # A, B, C …（アプリ内で使う統一ID）
    label: str   # 原本の記号（ア、①、(1) など）
    text: str


@dataclass
class ParsedQuestion:
    number: int
    occurrence: int                 # 同じ番号が何回目に出たか（章ごとの振り直し対策）
    chapter: str = ""
    chapter_no: int | None = None   # --chapter-pages で章を決めたときの章番号（問題IDに使う）
    category: str = ""
    page: int = 0
    y: float = 0.0
    end_page: int = 0
    question_lines: list[str] = field(default_factory=list)
    options: list[Option] = field(default_factory=list)
    option_family: str | None = None
    raw_lines: list[str] = field(default_factory=list)
    images: list[dict] = field(default_factory=list)
    answer_raw: str | None = None
    answer_tokens: list[str] = field(default_factory=list)   # 原本の記号のまま
    numeric_answer: dict | None = None
    answer_page: int | None = None
    answer_source: str = "answer_page"   # answer_page（原本の解答ページ） | answer_key（別紙の正解一覧）
    explanation_lines: list[str] = field(default_factory=list)
    ocr: bool = False
    ai: bool = False
    issues: list[dict] = field(default_factory=list)

    @property
    def question(self) -> str:
        return "\n".join(self.question_lines).strip()


@dataclass
class ParsedAnswer:
    number: int
    occurrence: int
    page: int
    raw: str
    tokens: list[str]
    numeric: dict | None
    explanation_lines: list[str] = field(default_factory=list)
    chapter: str = ""               # 解答部の「第1章の解答・解説」見出しから


def _issue(code: str, level: str, msg: str) -> dict:
    return {"code": code, "level": level, "message": msg}


# ---------- 前処理 ----------
def _flatten(pages_json: dict) -> list[dict]:
    """全ページの行を1列に並べ、ヘッダー・フッター・ページ番号を除く。"""
    pages = pages_json["pages"]
    counts = Counter()
    for p in pages:
        for t in {norm(l["text"]) for l in p["lines"]}:
            counts[t] += 1
    n = len(pages)
    repeated = {t for t, c in counts.items() if n >= 3 and c >= max(3, n * 0.5) and not Q_START.match(t)}
    rows = []
    for p in pages:
        for l in p["lines"]:
            t = norm(l["text"])
            if p["method"] == "ocr":
                t = OCR_LEAD_JUNK.sub("", t)
            if not t or PAGE_NUMBER.match(t) or t in repeated:
                continue
            rows.append({"text": t, "page": p["page"], "y": l["y0"], "ocr": p["method"] == "ocr",
                         "ai": p["method"] == "ai_assisted"})
    return rows


def _is_answer_header(t: str) -> bool:
    t2 = re.sub(r"\s", "", t)
    if INLINE_ANSWER.match(t2) or EXPLANATION.match(t2) and len(t2) > 2:
        return False  # 「正解：イ」「解説：…」は各問題の直後に置かれた解答
    if ANSWER_HEADER.match(t2):
        return True
    # OCRで崩れた見出し（例「解答・朋を説」）も短い行なら拾う。「解答群」は選択肢の見出しなので除外
    return len(t2) <= 10 and ("解答" in t2 or "正解" in t2) and "解答群" not in t2 and not Q_START.match(t2)


def _find_answer_start(rows: list[dict], allow_restart: bool = True) -> tuple[int | None, str]:
    for i, r in enumerate(rows):
        if _is_answer_header(r["text"]):
            return i, "header"
    # 見出しが無い場合：問題番号が振り出しに戻った位置を解答部の開始とみなす
    if any(INLINE_ANSWER.match(r["text"]) for r in rows):
        return None, "none"  # 各問題の直後に解答がある形式
    if not allow_restart:
        return None, "none"  # 章ごとに番号が戻る本（--chapter-pages）では「1に戻った」を解答部の目印にできない
    last = 0
    for i, r in enumerate(rows):
        if CHAPTER.match(r["text"]):
            last = 0  # 章ごとの振り直しは解答部の開始ではない
            continue
        m = Q_START.match(r["text"])
        if m:
            n = int(m.group(1) or m.group(2))
            if n < last and n == 1:
                return i, "restart"
            last = n
    return None, "none"


# ---------- 選択肢 ----------
def _marker_at_start(text: str, loose: bool) -> tuple[str, int, int] | None:
    """行頭の選択肢記号を探す。戻り値 (family, index, 記号の後ろの位置)。"""
    for fam, marks in FAMILIES.items():
        for idx, mk in enumerate(marks):
            cand = [mk] + [k for k, v in OCR_CONFUSION.items() if v == mk and loose]
            for c in cand:
                if text.startswith(c):
                    rest = text[len(c):]
                    if not rest:
                        continue
                    if re.match(SEP, rest) or fam in ("circled", "paren") or (loose and fam == "kana"):
                        return fam, idx, len(c)
    if loose:
        # OCRでは行頭に余白の汚れ（「第 ①…」「(④ …」など）が1〜2文字付くことがある。丸数字だけは読み飛ばして判定する
        m = re.match(r"^[^①-⑧]{1,3}?\s*([①-⑧])", text)
        if m and m.start(1) <= 4:
            return "circled", FAMILIES["circled"].index(m.group(1)), m.end(1)
    return None


def _split_inline(text: str, fam: str, start_idx: int, loose: bool) -> list[tuple[int, str]]:
    """「ア 1台　イ 2台　ウ 3台」のように1行に並んだ選択肢を分割する。"""
    marks = FAMILIES[fam]
    parts: list[tuple[int, str]] = []
    idx, pos = start_idx, 0
    m0 = _marker_at_start(text, loose)
    assert m0
    pos = m0[2]
    cur_start = pos
    while idx + 1 < len(marks):
        nxt = marks[idx + 1]
        alts = [nxt] + [k for k, v in OCR_CONFUSION.items() if v == nxt and loose]
        found = -1
        for a in alts:
            if loose:
                j = text.find(a, cur_start + 1)
            else:
                mm = re.search(rf"[\s　]{re.escape(a)}{SEP if fam in ('kana', 'latin') else ''}", text[cur_start:])
                j = cur_start + mm.start() + 1 if mm else -1
            if j > cur_start and (found == -1 or j < found):
                found = j
        if found == -1:
            break
        parts.append((idx, text[cur_start:found]))
        idx += 1
        cur_start = found + len(nxt)
    parts.append((idx, text[cur_start:]))
    return [(i, re.sub(rf"^{SEP}+", "", t).strip()) for i, t in parts]


# ---------- 解答 ----------
def _parse_answer_text(seg: str) -> tuple[list[str], dict | None, str]:
    """解答部分の文字列 → (記号トークン, 数値解答, 残り＝解説の書き出し)"""
    s = re.sub(r"^[\s.:、)]+", "", seg)
    s = re.sub(r"^(正解|答え)\s*[:]?\s*", "", s)
    m = ANS_TOKENS.match(s)
    if m:
        toks = re.findall(ANS_MARK, m.group(1))
        rest = s[m.end():]
        return toks, None, rest
    m = ANS_NUMERIC.match(s)
    if m:
        num = {"value": float(m.group(1)), "unit": m.group(2) or None, "tolerance": 0}
        return [], num, s[m.end():]
    return [], None, s


def _clean_expl(t: str) -> str:
    t = re.sub(r"^[\s。.]+", "", t)
    m = EXPLANATION.match(t)
    return (m.group(1) if m else t).strip()


def parse_answers(rows: list[dict]) -> tuple[list[ParsedAnswer], list[dict]]:
    answers: list[ParsedAnswer] = []
    stray: list[dict] = []
    seen = Counter()
    cur: ParsedAnswer | None = None
    chapter = ""
    for r in rows:
        t = r["text"]
        cm = ANSWER_CHAPTER.search(t)
        if cm:
            chapter = f"第{int(cm.group(1))}章"
            continue
        hits = list(Q_ANY.finditer(t))
        if hits and hits[0].start() == 0:
            for k, h in enumerate(hits):
                seg = t[h.end(): hits[k + 1].start() if k + 1 < len(hits) else len(t)]
                n = int(h.group(1) or h.group(2))
                seen[n] += 1
                toks, num, rest = _parse_answer_text(seg)
                cur = ParsedAnswer(n, seen[n], r["page"], seg.strip(), toks, num, chapter=chapter)
                if rest.strip():
                    cur.explanation_lines.append(_clean_expl(rest))
                answers.append(cur)
        elif cur is not None:
            if _is_answer_header(t) or CHAPTER.match(t):
                continue
            e = _clean_expl(t)
            if e:
                cur.explanation_lines.append(e)
        else:
            stray.append({"page": r["page"], "text": t})
    return answers, stray


def _label(fam: str, i: int) -> str:
    """記号ファミリーのi番目（範囲外なら '?'）。選択肢が9個以上ある・順番が崩れたOCR結果でも止まらないようにする。"""
    return FAMILIES[fam][i] if 0 <= i < len(FAMILIES[fam]) else "?"


# ---------- 問題 ----------
def parse_questions(rows: list[dict]) -> list[ParsedQuestion]:
    qs: list[ParsedQuestion] = []
    seen = Counter()
    chapter, category = "", ""
    cur: ParsedQuestion | None = None
    mode = "question"  # question | options | explanation
    for r in rows:
        t, loose = r["text"], r["ocr"]
        cm = CHAPTER.match(t)
        if cm:
            chapter, category = f"第{cm.group(1)}章", cm.group(2).strip()
            cur = None
            continue
        qm = Q_START.match(t)
        if qm:
            n = int(qm.group(1) or qm.group(2))
            seen[n] += 1
            cur = ParsedQuestion(number=n, occurrence=seen[n], chapter=chapter, category=category,
                                 page=r["page"], y=r["y"], end_page=r["page"], ocr=loose, ai=r["ai"])
            cur.raw_lines.append(t)
            if qm.group(3).strip():
                cur.question_lines.append(qm.group(3).strip())
            qs.append(cur)
            mode = "question"
            continue
        if cur is None:
            continue
        cur.raw_lines.append(t)
        cur.end_page = r["page"]
        cur.ocr = cur.ocr or loose
        am = INLINE_ANSWER.match(t)
        if am:
            toks, num, rest = _parse_answer_text(am.group(1))
            cur.answer_raw, cur.answer_tokens, cur.numeric_answer, cur.answer_page = am.group(1), toks, num, r["page"]
            if rest.strip():
                cur.explanation_lines.append(_clean_expl(rest))
            mode = "explanation"
            continue
        em = EXPLANATION.match(t)
        if em:
            if em.group(1):
                cur.explanation_lines.append(em.group(1))
            mode = "explanation"
            continue
        if mode == "explanation":
            cur.explanation_lines.append(t)
            continue
        mk = _marker_at_start(t, loose)
        if not mk and loose and cur.option_family in (None, "circled"):
            # 丸数字が「1」と読まれた行は、問題文の指示（〜なさい）の後か選択肢の続きで、番号が次の選択肢と一致するときだけ選択肢とみなす
            dm = OCR_DIGIT_OPTION.match(t)
            after_prompt = mode == "options" or any("なさい" in x for x in cur.question_lines[-2:])
            if dm and after_prompt and int(dm.group(1)) == len(cur.options) + 1:
                mk = ("circled", len(cur.options), dm.end())
                t = FAMILIES["circled"][mk[1]] + t[dm.end():]
                mk = ("circled", mk[1], 1)
        if mk:
            fam, idx, _ = mk
            expected = len(cur.options) if cur.option_family in (None, fam) else -1
            if idx == expected and (cur.option_family in (None, fam)):
                for i, txt in _split_inline(t, fam, idx, loose):
                    cur.options.append(Option(chr(ord("A") + i), FAMILIES[fam][i], txt))
                cur.option_family = fam
                mode = "options"
                continue
            if mode == "options" and idx != expected:
                cur.issues.append(_issue("OPTION_ORDER", "error",
                                         f"選択肢の順番が飛んでいます（期待: {_label(fam, expected)}、実際: {_label(fam, idx)}）"))
                cur.options.append(Option(chr(ord("A") + idx), FAMILIES[fam][idx], t[mk[2]:].strip()))
                continue
        if mode == "options" and cur.options:
            cur.options[-1].text += t  # 複数行にまたがる選択肢
        else:
            cur.question_lines.append(t)
    return qs


def _attach_images(qs: list[ParsedQuestion], pages_json: dict, answer_start_pos: tuple[int, float] | None) -> None:
    """問題の開始位置〜次の問題の開始位置の間にある画像をその問題に付ける。"""
    starts = [((q.page, q.y), q) for q in qs]
    for p in pages_json["pages"]:
        for img in p["images"]:
            pos = (p["page"], img["y0"])
            if answer_start_pos and pos >= answer_start_pos:
                continue
            owner = None
            for (sp, q) in starts:
                if sp <= pos:
                    owner = q
                else:
                    break
            if owner:
                owner.images.append({"path": img["path"], "page": p["page"], "bbox": [img["x0"], img["y0"], img["x1"], img["y1"]]})


def _to_tf(tok: str) -> str | None:
    if tok in TF_TRUE:
        return "T"
    if tok in TF_FALSE:
        return "F"
    return None


def link(qs: list[ParsedQuestion], answers: list[ParsedAnswer]) -> list[dict]:
    """問題と解答を (番号, 出現回数) で紐付ける。戻り値は紐付かなかった解答など全体の問題点。"""
    global_issues: list[dict] = []
    # 問題も解答も章が分かっていれば (章, 番号) で、そうでなければ (番号, 出現回数) で紐付ける
    by_chapter = bool(answers) and all(a.chapter for a in answers) and all(q.chapter_no for q in qs)
    keys = [((a.chapter, a.number) if by_chapter else (a.number, a.occurrence)) for a in answers]
    dup = {k for k, c in Counter(keys).items() if c > 1}  # 章の見出しを読み落とすと同じ番号が重なる。どれが正しいか分からないので使わない
    by_key = {k: a for k, a in zip(keys, answers) if k not in dup}
    for k in sorted(dup, key=str):
        global_issues.append(_issue("ANSWER_AMBIGUOUS", "warning",
                                    f"解答部に {k[0] if by_chapter else ''}問{k[1] if by_chapter else k[0]} が複数あるため、どれも紐付けていません"))
    used = set()
    for q in qs:
        a = by_key.get((q.chapter, q.number) if by_chapter else (q.number, q.occurrence))
        if q.answer_raw is None:
            if a is None:
                q.issues.append(_issue("NO_ANSWER", "error", "原本の解答が見つかりません"))
            else:
                used.add(id(a))
                q.answer_raw, q.answer_tokens, q.numeric_answer, q.answer_page = a.raw, a.tokens, a.numeric, a.page
                if a.explanation_lines and not q.explanation_lines:
                    q.explanation_lines = a.explanation_lines
        elif a is not None:
            used.add(id(a))
        if a is not None and not q.explanation_lines and a.explanation_lines:
            q.explanation_lines = a.explanation_lines
    for k, a in zip(keys, answers):
        if id(a) not in used and k not in dup:
            global_issues.append(_issue("ANSWER_WITHOUT_QUESTION", "error",
                                        f"解答 {a.chapter}問{a.number}（{a.page}ページ）に対応する問題がありません"))
    return global_issues


def assign_chapters(qs: list[ParsedQuestion], chapter_pages: list[int]) -> None:
    """--chapter-pages（各章が始まるPDFのページ）から問題の章を決める。章の見出しが読めない本向け。"""
    starts = sorted(chapter_pages)
    for q in qs:
        k = sum(1 for s in starts if s <= q.page)
        if k:
            q.chapter, q.chapter_no = f"第{k}章", k


def apply_answer_key(qs: list[ParsedQuestion], key: dict[tuple[str, int], list[str]]) -> list[dict]:
    """別紙の正解一覧で正解を決める。一覧にあるのに見つからない問題は全体の指摘にする。"""
    issues: list[dict] = []
    seen = set()
    for q in qs:
        k = (q.chapter, q.number)
        if k in seen:
            q.issues.append(_issue("DUPLICATE_NUMBER", "error", f"{q.chapter}第{q.number}問 が2回見つかりました"))
        seen.add(k)
        toks = key.get(k)
        if toks is None:
            q.issues.append(_issue("NOT_IN_ANSWER_KEY", "error", f"正解一覧に {q.chapter}第{q.number}問 がありません"))
            continue
        if q.answer_tokens and q.answer_tokens != toks:
            q.issues.append(_issue("ANSWER_KEY_DIFFERS", "warning",
                                   f"解答ページの読み取り（{''.join(q.answer_tokens)}）と正解一覧（{''.join(toks)}）が違います。正解一覧を使いました"))
        q.answer_raw, q.answer_tokens, q.numeric_answer, q.answer_page = "".join(toks), toks, None, None
        q.answer_source = "answer_key"
    missing = [k for k in key if k not in seen]
    for ch, n in missing:
        issues.append(_issue("QUESTION_NOT_FOUND", "error", f"正解一覧にある {ch}第{n}問 が問題ページから見つかりません"))
    return issues


def parse_pages(pages_json: dict, *, chapter_pages: list[int] | None = None,
                answer_key: dict[tuple[str, int], list[str]] | None = None) -> dict:
    rows = _flatten(pages_json)
    a_idx, how = _find_answer_start(rows, allow_restart=not chapter_pages)
    q_rows = rows if a_idx is None else rows[:a_idx]
    skip = 1 if how == "header" and not ANSWER_CHAPTER.search(rows[a_idx]["text"]) else 0  # 「第1章の解答・解説」は章の情報として残す
    a_rows = [] if a_idx is None else rows[a_idx + skip:]
    qs = parse_questions(q_rows)
    answers, stray = parse_answers(a_rows)
    _attach_images(qs, pages_json, (rows[a_idx]["page"], rows[a_idx]["y"]) if a_idx is not None else None)
    if chapter_pages:
        assign_chapters(qs, chapter_pages)
    global_issues = link(qs, answers)
    if answer_key:
        global_issues = [i for i in global_issues if i["code"] != "ANSWER_WITHOUT_QUESTION"]  # 正解は一覧から取る
        for q in qs:
            q.issues = [i for i in q.issues if i["code"] != "NO_ANSWER"]
        global_issues += apply_answer_key(qs, answer_key)
    if chapter_pages:
        # スキャンの順番が前後していても、章・問題番号の順に並べる
        qs.sort(key=lambda q: (q.chapter_no or 0, q.number, q.occurrence))
    if a_idx is None and not any(q.answer_raw for q in qs):
        global_issues.append(_issue("NO_ANSWER_SECTION", "error", "解答ページが見つかりません"))
    elif how == "restart":
        global_issues.append(_issue("ANSWER_SECTION_GUESSED", "warning",
                                    "「解答」見出しが無いため、問題番号が1に戻った位置を解答部とみなしました"))
    if stray:
        global_issues.append(_issue("UNPARSED_ANSWER_LINES", "warning",
                                    f"解答部に解析できない行が{len(stray)}行あります（先頭: {stray[0]['text'][:30]}）"))
    return {
        "source_pdf": pages_json["source_pdf"],
        "answer_section": {"found_by": how, "page": rows[a_idx]["page"] if a_idx is not None else None},
        "questions": [{**asdict(q), "question": q.question} for q in qs],
        "answers_count": len(answers),
        "issues": global_issues,
    }


def parse_file(pages_path: str | Path, out_path: str | Path, **kw) -> dict:
    pages_json = json.loads(Path(pages_path).read_text(encoding="utf-8"))
    result = parse_pages(pages_json, **kw)
    Path(out_path).write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    return result
