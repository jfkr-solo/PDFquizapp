"""STEP 6: サンプルPDFでの動作確認テスト。  実行: python -m pytest -q"""
from __future__ import annotations

import copy
import json
import shutil
from types import SimpleNamespace

import pytest

from pipeline.ai_assist import AIOption, AIPage, AIQuestion, AIResult, assist_pages, pages_needing_help
from pipeline.build_json import build_book
from pipeline.extract import extract_pdf, find_tessdata
from pipeline.parse import parse_pages
from pipeline.validate import validate_book
from tests.make_sample_pdf import make_scan_pdf, make_text_pdf

needs_ocr = pytest.mark.skipif(find_tessdata() is None or shutil.which("tesseract") is None,
                               reason="Tesseract（jpn）が未インストール")


@pytest.fixture(scope="module")
def sample(tmp_path_factory):
    d = tmp_path_factory.mktemp("sample")
    make_text_pdf(d / "text.pdf")
    make_scan_pdf(d / "text.pdf", d / "scan.pdf")
    return d


def convert(pdf, out, **kw):
    pages = extract_pdf(pdf, out)
    parsed = parse_pages(pages)
    book = build_book(parsed, book_id="T01", title="テスト", pdf_path=pdf, out_dir=out, **kw)
    res = validate_book(book, book_dir=out, pages_json=pages)
    return pages, parsed, res


def codes(q):
    return {i["code"] for i in q["validation_issues"]}


# ---------- STEP 2 ----------
def test_extract_text_pdf(sample, tmp_path):
    pages = extract_pdf(sample / "text.pdf", tmp_path)
    assert pages["source_pdf"]["pages"] == 3
    assert [p["method"] for p in pages["pages"]] == ["text", "text", "text"]
    texts = [l["text"] for l in pages["pages"][0]["lines"]]
    assert "問1 OSI参照モデルで、IPが属する層はどれか。" in texts
    assert len(pages["pages"][0]["images"]) == 1
    assert (tmp_path / pages["pages"][0]["images"][0]["path"]).is_file()
    assert (tmp_path / "pages.json").is_file()


@needs_ocr
def test_extract_scan_pdf_uses_ocr(sample, tmp_path):
    pages = extract_pdf(sample / "scan.pdf", tmp_path)
    assert all(p["method"] == "ocr" for p in pages["pages"])
    assert all(p["images"] == [] for p in pages["pages"])  # ページ全体のスキャン画像は図扱いしない
    assert any("ネットワーク" in l["text"] for l in pages["pages"][0]["lines"])


def test_extract_missing_file(tmp_path):
    from pipeline.extract import ExtractError
    with pytest.raises(ExtractError):
        extract_pdf(tmp_path / "none.pdf", tmp_path)


# ---------- STEP 3〜5（テキストPDF） ----------
def test_text_pdf_end_to_end(sample, tmp_path):
    _, parsed, res = convert(sample / "text.pdf", tmp_path, expected_question_count=6)
    assert res["schema_errors"] == []
    book = res["book"]
    qs = {q["source"]["question_number"]: q for q in book["questions"]}
    assert len(qs) == 6 and parsed["answers_count"] == 6
    assert qs[1]["question_type"] == "single_choice" and qs[1]["correct_answers"] == ["C"]
    assert qs[2]["question_type"] == "multiple_choice" and qs[2]["correct_answers"] == ["A", "B", "C"]
    assert [o["text"] for o in qs[3]["options"]] == ["1台", "2台", "3台", "4台"]   # 1行に並んだ選択肢
    assert qs[3]["images"] and (tmp_path / qs[3]["images"][0]["path"]).is_file()
    assert qs[4]["question_type"] == "true_false" and qs[4]["correct_answers"] == ["F"]
    assert qs[5]["question_type"] == "numeric" and qs[5]["numeric_answer"]["value"] == 4
    assert qs[6]["explanation"] == "" and "V_NO_EXPLANATION" in codes(qs[6])
    assert {q["validation_status"] for q in book["questions"]} == {"auto_ok"}
    assert qs[1]["source"] == {**qs[1]["source"], "page": 1, "answer_page": 3}
    assert qs[1]["audio_text"].startswith("問題1。") and "ウ、ネットワーク層" in qs[1]["audio_answer_text"]


# ---------- STEP 5：壊したデータを検出できるか ----------
def test_validator_detects_broken_data(sample, tmp_path):
    pages, _, res = convert(sample / "text.pdf", tmp_path)
    book = copy.deepcopy(res["book"])
    q = book["questions"]
    q[0]["options"] = q[0]["options"][:1]                      # 選択肢の欠落
    q[1]["correct_answers"] = ["A", "Z"]                        # 選択肢に無い正解
    q[2]["question"] += "〓"                                    # 判読不能文字
    q[2]["images"][0]["path"] = "images/missing.png"            # 画像ファイルが無い
    q[3]["source"]["page"] = 99                                 # ページ範囲外
    q[4]["source"]["question_number"] = 9                       # 番号の飛び
    q[5]["question"], q[5]["options"] = q[0]["question"], q[0]["options"]  # 重複
    q[5]["explanation"] = "正解はアである。"                      # 解説と正解の矛盾（正解はウ）
    out = validate_book(book, book_dir=tmp_path, pages_json=pages)["book"]["questions"]
    assert "V_OPTIONS_MISSING" in codes(out[0])
    assert "V_ANSWER_NOT_IN_OPTIONS" in codes(out[1])
    assert {"V_GARBLED", "V_IMAGE_NOT_FOUND"} <= codes(out[2])
    assert "V_PAGE_OUT_OF_RANGE" in codes(out[3])
    assert "V_NUMBER_SEQUENCE" in codes(out[4])
    assert {"V_DUPLICATE", "V_EXPLANATION_CONFLICT"} <= codes(out[5])
    assert all(x["validation_status"] == "pending" for x in out[:5])


def test_schema_blocks_publishable_question_without_answer(sample, tmp_path):
    _, _, res = convert(sample / "text.pdf", tmp_path)
    from pipeline.validate import schema_errors
    book = copy.deepcopy(res["book"])
    book["questions"][0]["correct_answers"] = []      # auto_ok のまま正解を消す
    assert any("questions/0/correct_answers" in e for e in schema_errors(book))


def test_verified_reverts_when_content_changes(sample, tmp_path):
    pages, _, res = convert(sample / "text.pdf", tmp_path)
    book = res["book"]
    q = book["questions"][0]
    q["validation_status"], q["verified_hash"] = "verified", q["content_hash"]
    book = validate_book(book, book_dir=tmp_path, pages_json=pages)["book"]
    assert book["questions"][0]["validation_status"] == "verified"
    book["questions"][0]["question"] = "書き換えた問題文"
    book = validate_book(book, book_dir=tmp_path, pages_json=pages)["book"]
    assert book["questions"][0]["validation_status"] == "pending"
    assert "V_CHANGED_AFTER_VERIFY" in codes(book["questions"][0])


# ---------- スキャンPDF：OCR由来は必ず要確認 ----------
@needs_ocr
def test_scan_pdf_is_never_auto_ok(sample, tmp_path):
    _, parsed, res = convert(sample / "scan.pdf", tmp_path)
    assert res["schema_errors"] == []
    qs = res["book"]["questions"]
    assert len(qs) == 6
    assert all(q["validation_status"] == "pending" for q in qs)
    assert all("OCR_SOURCE" in codes(q) for q in qs)
    fig = [q for q in qs if q["source"]["question_number"] == 3][0]
    assert fig["images"] and fig["images"][0]["kind"] == "page_region"


# ---------- 書式のバリエーション ----------
def _pages(*page_lines):
    return {"source_pdf": {"file": "x.pdf", "sha256": "0" * 64, "pages": len(page_lines)},
            "pages": [{"page": i + 1, "method": "text", "width": 595, "height": 842, "images": [], "warnings": [],
                       "char_count": sum(len(t) for t in lines),
                       "lines": [{"text": t, "x0": 50, "y0": 50 + 20 * k, "x1": 500, "y1": 60 + 20 * k} for k, t in enumerate(lines)]}
                      for i, lines in enumerate(page_lines)]}


def test_inline_answers_and_chapter_restart():
    pj = _pages(
        ["第1章 基礎", "問1 1+1は？", "① 1", "② 2", "正解：②", "解説：1+1=2。", "問2 2+2は？", "① 3", "② 4", "正解：②"],
        ["第2章 応用", "問1 3×3は？", "(1) 6", "(2) 9", "正解：(2)", "問2 東京は日本の首都である。○か×か。", "正解：○"],
    )
    parsed = parse_pages(pj)
    qs = parsed["questions"]
    assert [(q["chapter"], q["number"]) for q in qs] == [("第1章", 1), ("第1章", 2), ("第2章", 1), ("第2章", 2)]
    book = build_book(parsed, book_id="T02", title="t")
    out = validate_book(book, book_dir=".", pages_json=pj)
    assert out["schema_errors"] == []
    b = out["book"]["questions"]
    assert [q["correct_answers"] for q in b] == [["B"], ["B"], ["B"], ["T"]]
    assert b[0]["explanation"] == "1+1=2。"
    assert "V_NUMBER_SEQUENCE" not in codes(b[2])     # 章が変わって1に戻るのは正常


def test_answer_table_on_one_line_and_mismatch():
    pj = _pages(["問1 A?", "ア x", "イ y", "問2 B?", "ア x", "イ y", "問3 C?", "ア x", "イ y"],
                ["解答一覧", "問1 イ 問2 ア 問4 イ"])
    parsed = parse_pages(pj)
    qs = {q["number"]: q for q in parsed["questions"]}
    assert qs[1]["answer_tokens"] == ["イ"] and qs[2]["answer_tokens"] == ["ア"]
    assert any(i["code"] == "NO_ANSWER" for i in qs[3]["issues"])
    assert any(i["code"] == "ANSWER_WITHOUT_QUESTION" for i in parsed["issues"])


# ---------- AI補助：原文に無い文章は採用しない ----------
def test_ai_assist_drops_text_not_in_source():
    body = "【1】OSI参照モデルで、IPが属する層はどれか。 ア 物理層 イ ネットワーク層 " * 6
    pj = _pages(["IT基礎", body], ["解答", "問1 イ"])
    parsed = parse_pages(pj)
    assert pages_needing_help(pj, parsed) == [1]

    fake = AIResult(pages=[AIPage(page=1, questions=[AIQuestion(
        number=1, question="OSI参照モデルで、IPが属する層はどれか。",
        options=[AIOption(label="ア", text="物理層"), AIOption(label="イ", text="ネットワーク層"),
                 AIOption(label="ウ", text="AIが作った選択肢")])])])
    client = SimpleNamespace(messages=SimpleNamespace(parse=lambda **kw: SimpleNamespace(parsed_output=fake, stop_reason="end_turn")))
    pj2, log = assist_pages(copy.deepcopy(pj), [1], client)
    assert log[0]["dropped_lines"] == 1
    q = parse_pages(pj2)["questions"][0]
    assert [o["text"] for o in q["options"]] == ["物理層", "ネットワーク層"] and q["ai"]
    book = build_book(parse_pages(pj2), book_id="T03", title="t")
    item = validate_book(book, book_dir=".", pages_json=pj2)["book"]["questions"][0]
    assert item["correct_answers"] == ["B"]          # 正解は原本の解答ページ由来
    assert item["validation_status"] == "pending" and "AI_ASSISTED" in codes(item)
