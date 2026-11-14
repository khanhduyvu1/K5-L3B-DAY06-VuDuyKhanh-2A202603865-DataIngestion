"""Read and normalize source data.

Corpus: Vietnamese Labour Code 2012 and 2019 saved as HTML pages. HTML has no
physical pages, so the traceable unit is the article ("Điều"): ``page`` stores
the article number and ``metadata`` keeps year / chapter / article title.
"""
from __future__ import annotations

import re
import unicodedata
from pathlib import Path

from bs4 import BeautifulSoup

from .models import DocumentPage

ROMAN = {"I": 1, "V": 5, "X": 10, "L": 50, "C": 100}
CHAPTER_RE = re.compile(r"^Chương\s+([IVXLC]+)$")
ARTICLE_RE = re.compile(r"^Điều\s+(\d+)\.\s*(.*)$")
SECTION_RE = re.compile(r"^Mục\s+\d+\b")
END_RE = re.compile(r"^(Bộ luật này (đã )?được Quốc hội|CHỦ TỊCH QUỐC HỘI)")


def roman_to_int(value: str) -> int:
    total = 0
    for i, ch in enumerate(value):
        v = ROMAN[ch]
        total += -v if i + 1 < len(value) and ROMAN[value[i + 1]] > v else v
    return total


def normalize_text(text: str) -> str:
    """NFC Unicode, unify spaces/quotes, keep one paragraph per line."""
    text = unicodedata.normalize("NFC", text)
    text = text.replace(" ", " ").replace("​", "").replace("﻿", "")
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    lines = [line.strip() for line in text.split("\n")]
    return "\n".join(line for line in lines if line)


def _paragraphs(path: Path) -> list[str]:
    soup = BeautifulSoup(path.read_text(encoding="utf-8"), "html.parser")
    for tag in soup(["script", "style", "nav", "header", "footer"]):
        tag.decompose()
    out = []
    for p in soup.find_all("p"):
        if p.find_parent("li") or p.find_parent("table"):  # TOC notes / signature table
            continue
        text = normalize_text(p.get_text(" ")).replace("\n", " ")
        if text:
            out.append(text)
    return out


def load_html_law(path: Path, document_id: str, source: str, year: int,
                  expected_articles: int, log: list[dict]) -> list[DocumentPage]:
    """Split the law body into one DocumentPage per article, in order 1..N.

    An article heading is accepted only when its number is the next expected
    one; this ignores cross references such as "Điều 3. ..." quoted in text and
    the table of contents that precedes the body on some sites.
    """
    paras = _paragraphs(path)
    try:
        start = next(i for i, p in enumerate(paras) if p == "Chương I")
    except StopIteration as exc:
        raise ValueError(f"{path.name}: cannot find 'Chương I'") from exc
    log.append({"document_id": document_id, "event": "skip_preamble", "paragraphs": start})

    pages: list[DocumentPage] = []
    chapter, chapter_title, section = 0, "", ""
    expect_chapter_title = False
    current: dict | None = None

    def flush() -> None:
        if current is None:
            return
        body = normalize_text("\n".join(current["lines"]))
        if len(body) < 40:
            log.append({"document_id": document_id, "event": "short_article",
                        "dieu": current["dieu"], "chars": len(body)})
        pages.append(DocumentPage(
            document_id=document_id, source=source, page=current["dieu"], text=body,
            metadata={"year": year, "chuong": current["chuong"],
                      "chuong_title": current["chuong_title"], "muc": current["muc"],
                      "dieu": current["dieu"], "dieu_title": current["title"],
                      "document_type": "bo_luat"}))

    for p in paras[start:]:
        if END_RE.match(p):
            log.append({"document_id": document_id, "event": "stop_at_signature", "text": p[:80]})
            break
        m_ch = CHAPTER_RE.match(p)
        if m_ch:
            chapter, chapter_title, section = roman_to_int(m_ch.group(1)), "", ""
            expect_chapter_title = True
            continue
        if expect_chapter_title and not ARTICLE_RE.match(p) and not SECTION_RE.match(p):
            chapter_title = p
            expect_chapter_title = False
            continue
        if SECTION_RE.match(p) and current is not None:
            # "Mục 1. ..." headings belong to the next article, not the current body
            section = p
            continue
        m_art = ARTICLE_RE.match(p)
        next_no = (current["dieu"] + 1) if current else 1
        if m_art and int(m_art.group(1)) == next_no:
            flush()
            current = {"dieu": next_no, "title": m_art.group(2).strip(), "chuong": chapter,
                       "chuong_title": chapter_title, "muc": section,
                       "lines": [f"Điều {next_no}. {m_art.group(2).strip()}"]}
            expect_chapter_title = False
            continue
        if current is not None:
            current["lines"].append(p)
    flush()

    numbers = [pg.page for pg in pages]
    if numbers != list(range(1, expected_articles + 1)):
        missing = sorted(set(range(1, expected_articles + 1)) - set(numbers))
        raise ValueError(f"{document_id}: got {len(numbers)} articles, missing {missing[:10]}")
    return pages


def load_pdf(path: Path, document_id: str, source: str) -> list[DocumentPage]:
    """Extract each physical page; record empty pages (not used by this corpus)."""
    from pypdf import PdfReader

    pages = []
    for number, page in enumerate(PdfReader(path).pages, start=1):
        pages.append(DocumentPage(document_id, source, number, normalize_text(page.extract_text() or "")))
    return pages
