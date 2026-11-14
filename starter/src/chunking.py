"""Chunking strategies.

A  fixed_size_stream: fixed character windows over the whole document text,
   ignoring article boundaries (a chunk may span two articles).
B  by_article: one chunk per article ("Điều"); long articles are split on
   clause/point lines and every sub-chunk repeats the article heading (and the
   clause intro when a chunk starts with a lettered point) so it reads alone.
"""
from __future__ import annotations

import hashlib
import re

from .models import Chunk, DocumentPage

CLAUSE_RE = re.compile(r"^\d+\.\s")          # "1. ..."
POINT_RE = re.compile(r"^[a-zđ]\)\s")         # "a) ...", "đ) ..."


def content_hash(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:16]


def _base_metadata(page: DocumentPage) -> dict:
    return {k: page.metadata[k] for k in ("year", "chuong", "chuong_title", "dieu_title", "document_type")}


def fixed_size_stream(pages: list[DocumentPage], size: int = 500, overlap: int = 50,
                      strategy: str = "A") -> list[Chunk]:
    """Fixed windows of ``size`` characters with ``overlap`` over one document.

    The window end is moved back to the nearest space (within the last 20%) so
    words are not cut in half; otherwise boundaries ignore structure.
    """
    if not pages:
        return []
    if overlap >= size:
        raise ValueError("overlap must be smaller than size")
    spans, parts, pos = [], [], 0
    for page in pages:
        spans.append((pos, pos + len(page.text), page))
        parts.append(page.text)
        pos += len(page.text) + 1
    text = "\n".join(parts)

    chunks: list[Chunk] = []
    start = 0
    while start < len(text):
        end = min(start + size, len(text))
        if end < len(text):
            cut = text.rfind(" ", start + int(size * 0.8), end)
            end = cut if cut > start else end
        covered = [pg for s, e, pg in spans if s < end and e > start]
        body = text[start:end].strip()
        first = covered[0]
        meta = _base_metadata(first)
        meta.update({"pages": [pg.page for pg in covered], "char_start": start, "char_end": end})
        chunks.append(Chunk(
            chunk_id=f"{strategy}:{first.document_id}:{len(chunks):04d}",
            document_id=first.document_id, source=first.source, page=first.page,
            text=body, metadata=meta))
        if end >= len(text):
            break
        start = max(end - overlap, start + 1)
    return chunks


def _split_long_line(line: str, budget: int) -> list[str]:
    """Split one very long clause on sentence / semicolon boundaries, then hard."""
    pieces, buf = [], ""
    for part in re.split(r"(?<=[;.])\s+", line):
        if len(buf) + len(part) + 1 <= budget:
            buf = f"{buf} {part}".strip()
            continue
        if buf:
            pieces.append(buf)
        while len(part) > budget:
            cut = part.rfind(" ", 0, budget)
            cut = cut if cut > 0 else budget
            pieces.append(part[:cut])
            part = part[cut:].strip()
        buf = part
    if buf:
        pieces.append(buf)
    return pieces


def by_article(page: DocumentPage, max_size: int = 1000, strategy: str = "B") -> list[Chunk]:
    """Keep a whole article when it fits; otherwise pack clause lines greedily."""
    lines = page.text.split("\n")
    header, body = lines[0], lines[1:]
    groups: list[str] = []
    if len(page.text) <= max_size:
        groups = [page.text]
    else:
        current: list[str] = []          # header/prefix lines are included
        clause_intro = ""
        budget = max_size - len(header) - 205  # room left after header + clause intro

        def start(first_line: str) -> list[str]:
            pre = [header]
            if POINT_RE.match(first_line) and clause_intro:
                pre.append(clause_intro[:200] + ("…" if len(clause_intro) > 200 else ""))
            return pre + [first_line]

        for line in body:
            for piece in (_split_long_line(line, budget) if len(line) > budget else [line]):
                if not current:
                    current = start(piece)
                elif len("\n".join(current + [piece])) > max_size:
                    groups.append("\n".join(current))
                    current = start(piece)
                else:
                    current.append(piece)
            if CLAUSE_RE.match(line):
                clause_intro = line
        if current:
            groups.append("\n".join(current))
        if max(len(g) for g in groups) > max_size:
            raise AssertionError(f"{page.document_id} Điều {page.page}: chunk exceeds {max_size}")

    chunks = []
    for j, text in enumerate(groups):
        meta = _base_metadata(page)
        meta.update({"pages": [page.page], "part": j, "parts": len(groups)})
        chunks.append(Chunk(
            chunk_id=f"{strategy}:{page.document_id}:{page.page:03d}:{j}",
            document_id=page.document_id, source=page.source, page=page.page,
            text=text, metadata=meta))
    return chunks
