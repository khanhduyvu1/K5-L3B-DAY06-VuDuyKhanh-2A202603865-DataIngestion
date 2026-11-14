"""Day 06 pipeline: ingest -> chunk (A, B) -> embed -> pgvector -> retrieve A/B/C -> evaluate.

Run from ``starter/``:  python -m src.run
Outputs go to the repository root: data/manifest.json, results/*, results/audit/*.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import platform
import statistics
import time
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

from .chunking import by_article, content_hash, fixed_size_stream
from .embeddings import E5Embedder
from .evaluation import evaluate_query, gold_list, norm, summarize
from .ingestion import load_html_law
from .models import Chunk, DocumentPage
from .store import PgVectorStore

STARTER = Path(__file__).resolve().parents[1]
ROOT = STARTER.parent
RESULTS = ROOT / "results"

CORPUS = [
    {"source_id": "blld-2012", "title": "Bộ luật Lao động số 10/2012/QH13", "year": 2012,
     "file": "starter/data/blld-2012_caselaw.html",
     "url": "https://caselaw.vn/van-ban-phap-luat/115774-bo-luat-lao-dong-so-10-2012-qh13-ngay-18-06-2012-cua-quoc-hoi",
     "expected_articles": 242, "accessed_at": "2026-11-14",
     "snapshot": "Toàn văn gốc ngày 18/06/2012 (hết hiệu lực từ 01/01/2021); chú thích hướng dẫn của caselaw.vn nằm ở mục lục và bị loại."},
    {"source_id": "blld-2019", "title": "Bộ luật Lao động số 45/2019/QH14", "year": 2019,
     "file": "starter/data/blld-2019_pbgdpl-cantho.html",
     "url": "https://pbgdpl.cantho.gov.vn/attachment/261",
     "expected_articles": 220, "accessed_at": "2026-11-14",
     "snapshot": "Toàn văn gốc thông qua 20/11/2019, hiệu lực 01/01/2021; không gồm các sửa đổi sau này."},
]
LICENSE = ("Văn bản quy phạm pháp luật không thuộc đối tượng bảo hộ quyền tác giả "
           "(Điều 15 Luật Sở hữu trí tuệ). Chỉ dùng phần thân văn bản luật, không dùng phần biên tập/chú thích của trang web.")

CHUNK_A = {"size": 500, "overlap": 50}
CHUNK_B = {"max_size": 1000}
STRATEGIES = {
    "A": {"index": "A", "chunking": f"fixed_size_stream size={CHUNK_A['size']} overlap={CHUNK_A['overlap']} (bỏ qua ranh giới Điều)", "filter": False},
    "B": {"index": "B", "chunking": f"by_article max_size={CHUNK_B['max_size']} (giữ Điều, tách theo khoản, lặp tiêu đề)", "filter": False},
    "C": {"index": "B", "chunking": "giống B (dùng chung index B)", "filter": True},
}
TOP_K = 3
COHERENCE_ARTICLES = [("blld-2019", n) for n in range(1, 221, 22)]  # 1, 23, ..., 199: chosen before scoring


def dump(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2, default=str), encoding="utf-8")


def ingest(log: list[dict]) -> dict[str, list[DocumentPage]]:
    docs = {}
    for c in CORPUS:
        pages = load_html_law(ROOT / c["file"], c["source_id"], c["url"], c["year"],
                              c["expected_articles"], log)
        docs[c["source_id"]] = pages
    return docs


def write_manifest(docs: dict[str, list[DocumentPage]]) -> dict:
    entries = []
    for c in CORPUS:
        pages = docs[c["source_id"]]
        chars = [len(p.text) for p in pages]
        entries.append({
            "source_id": c["source_id"], "title": c["title"], "year": c["year"],
            "source_path_or_url": c["url"], "local_file": c["file"],
            "license_or_permission": LICENSE, "accessed_at": c["accessed_at"], "snapshot": c["snapshot"],
            "unit": "Điều (article); page = số Điều", "unit_count": len(pages),
            "unit_ids": [p.page for p in pages], "chars_total": sum(chars),
            "chars_per_unit": {p.page: len(p.text) for p in pages},
            "units_ge_1500_chars": sum(x >= 1500 for x in chars),
            "chapters": len({p.metadata["chuong"] for p in pages}),
        })
    manifest = {
        "corpus": "Bộ luật Lao động Việt Nam 2012 và 2019",
        "counting_rule": ("HTML không có trang vật lý. Theo GUIDE §1, mỗi Điều là một đơn vị nguồn độc lập có ý nghĩa; "
                          "page = số Điều. Chỉ tính thân văn bản từ 'Chương I' đến trước câu thông qua/chữ ký; "
                          "loại menu web, mục lục, chú thích của trang và bảng chữ ký."),
        "totals": {"units": sum(e["unit_count"] for e in entries),
                   "chars": sum(e["chars_total"] for e in entries),
                   "approx_a4_pages_at_3000_chars": sum(e["chars_total"] for e in entries) // 3000},
        "documents": entries,
    }
    dump(ROOT / "data" / "manifest.json", manifest)
    # Clean law text only (public-domain legal text, no website content) for reviewers.
    with (ROOT / "data" / "corpus_articles.jsonl").open("w", encoding="utf-8") as f:
        for pages in docs.values():
            for p in pages:
                f.write(json.dumps({"document_id": p.document_id, "source": p.source, "page": p.page,
                                    **p.metadata, "text": p.text}, ensure_ascii=False) + "\n")
    return manifest


def validate_benchmark(questions: list[dict], docs: dict[str, list[DocumentPage]]) -> list[dict]:
    by_id = {(d, p.page): p for d, pages in docs.items() for p in pages}
    report, failed = [], []
    for q in questions:
        for g in gold_list(q):
            page = by_id.get((g["source_id"], g["page"]))
            ok = page is not None and all(norm(x) in norm(page.text) for x in g["quotes"])
            report.append({"id": q["id"], "source_id": g["source_id"], "page": g["page"], "evidence_found": ok})
            if not ok:
                failed.append((q["id"], g["source_id"], g["page"]))
    splits = {s: sum(q["split"] == s for q in questions) for s in ("dev", "test")}
    filt = {s: sum(bool(q.get("filter")) and q["split"] == s for q in questions) for s in ("dev", "test")}
    summary = {"questions": len(questions), "splits": splits, "filter_questions": filt, "checks": report}
    dump(RESULTS / "benchmark_validation.json", summary)
    if failed:
        raise SystemExit(f"Gold evidence not found in source: {failed}")
    if len(questions) < 20 or splits["dev"] < 15 or splits["test"] < 5 or sum(filt.values()) < 3 or filt["test"] < 1:
        raise SystemExit(f"Benchmark does not meet minimums: {splits} {filt}")
    return report


def build_chunks(docs: dict[str, list[DocumentPage]]) -> dict[str, list[Chunk]]:
    a, b = [], []
    for pages in docs.values():
        a += fixed_size_stream(pages, CHUNK_A["size"], CHUNK_A["overlap"], "A")
        for p in pages:
            b += by_article(p, CHUNK_B["max_size"], "B")
    return {"A": a, "B": b}


def chunk_stats(chunks: list[Chunk], tokens: list[int], max_tokens: int) -> dict:
    lengths = [len(c.text) for c in chunks]
    return {"count": len(chunks), "chars_total": sum(lengths), "chars_min": min(lengths),
            "chars_median": statistics.median(lengths), "chars_mean": round(statistics.mean(lengths), 1),
            "chars_max": max(lengths), "tokens_total": sum(tokens), "tokens_max": max(tokens),
            "chunks_over_model_max_tokens": sum(t > max_tokens for t in tokens),
            "multi_article_chunks": sum(len(c.metadata["pages"]) > 1 for c in chunks)}


def index_strategy(store: PgVectorStore, embedder: E5Embedder, name: str, chunks: list[Chunk]) -> dict:
    """Embed only new/changed chunks, upsert, delete stale chunks; return timing."""
    existing = store.existing_hashes(name)
    todo = [c for c in chunks if existing.get(c.chunk_id) != content_hash(c.text)]
    t0 = time.perf_counter()
    vectors = embedder.embed_documents([c.text for c in todo]) if todo else []
    t_embed = time.perf_counter() - t0
    t1 = time.perf_counter()
    # keep_ids = every current chunk, so unchanged rows survive and only stale ones are deleted.
    res = store.upsert(name, todo, vectors, document_ids=[c["source_id"] for c in CORPUS],
                       keep_ids=[c.chunk_id for c in chunks])
    t_store = time.perf_counter() - t1
    return {"embedded": len(todo), "skipped_unchanged": len(chunks) - len(todo),
            "embed_seconds": round(t_embed, 2), "store_seconds": round(t_store, 2), "upsert": res}


def run_queries(store: PgVectorStore, embedder: E5Embedder, questions: list[dict]) -> list[dict]:
    traces = []
    qvecs = {q["id"]: embedder.embed_query(q["question"]) for q in questions}
    for name, cfg in STRATEGIES.items():
        for q in questions:
            applied = q.get("filter") if cfg["filter"] and q.get("filter") else None
            t0 = time.perf_counter()
            hits = store.search(cfg["index"], qvecs[q["id"]], TOP_K, applied)
            ms = (time.perf_counter() - t0) * 1000
            ev = evaluate_query(q, hits, applied)
            for h in ev["hits"]:
                h["score"] = round(float(h["score"]), 4)
            traces.append({"strategy": name, "id": q["id"], "split": q["split"], "type": q["type"],
                           "question": q["question"], "expected_answer": q["expected_answer"],
                           "gold": [{k: g[k] for k in ("source_id", "page", "quotes")} for g in gold_list(q)],
                           "question_filter": q.get("filter"), "search_ms": round(ms, 1), **ev})
    with (RESULTS / "traces.jsonl").open("w", encoding="utf-8") as f:
        for t in traces:
            f.write(json.dumps(t, ensure_ascii=False, default=str) + "\n")
    return traces


def write_summary_md(summary: dict, stats: dict, timing: dict) -> None:
    lines = ["# Kết quả retrieval (tự động)", "",
             "| Strategy | Split | Hit@1 (n/N) | Evidence Hit@3 (n/N) | Filter tuân thủ top-3 (n/N) | Câu trượt Hit@3 |",
             "|---|---|---|---|---|---|"]
    for s in STRATEGIES:
        for split in ("dev", "test", "all"):
            r = summary[s][split]
            fc = f"{r['filter_compliant']}/{r['filter_questions']}" if r["filter_questions"] else "N/A"
            lines.append(f"| {s} | {split} | {r['hit1']}/{r['n']} | {r['hit3']}/{r['n']} | {fc} | {', '.join(r['misses']) or '—'} |")
    lines += ["", "| Index | Chunk | Ký tự TB | Max ký tự | Token max | Chunk > 512 token | Chunk nhiều Điều | Embed (s) |",
              "|---|---|---|---|---|---|---|---|"]
    for s, st in stats.items():
        lines.append(f"| {s} | {st['count']} | {st['chars_mean']} | {st['chars_max']} | {st['tokens_max']} | "
                     f"{st['chunks_over_model_max_tokens']} | {st['multi_article_chunks']} | {timing[s]['embed_seconds']} |")
    (RESULTS / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_audit_sheets(traces: list[dict], chunks: dict[str, list[Chunk]],
                       docs: dict[str, list[DocumentPage]]) -> None:
    audit = RESULTS / "audit"
    audit.mkdir(parents=True, exist_ok=True)
    # 1) Coherence: 10 fixed source positions (middle line of chosen articles).
    rows = []
    for doc_id, art in COHERENCE_ARTICLES:
        pages = docs[doc_id]
        offset = sum(len(p.text) + 1 for p in pages if p.page < art)
        page = next(p for p in pages if p.page == art)
        mid = len(page.text) // 2
        line_start = page.text.rfind("\n", 0, mid) + 1
        line = page.text[line_start:page.text.find("\n", mid) if "\n" in page.text[mid:] else None]
        pos = offset + mid
        a = next(c for c in chunks["A"] if c.document_id == doc_id and c.metadata["char_start"] <= pos < c.metadata["char_end"])
        b = next(c for c in chunks["B"] if c.document_id == doc_id and c.page == art and line[:60] in c.text)
        for strat, ch in (("A", a), ("B", b), ("C", b)):
            rows.append({"position_id": f"{doc_id}:D{art}:mid", "anchor_line": line[:120], "strategy": strat,
                         "chunk_id": ch.chunk_id, "chunk_text": ch.text, "score_0_2": "", "reason": ""})
    _write_csv(audit / "coherence_sheet.csv", rows)
    # 2) Metadata: test questions x top-3 x strategy.
    rows = []
    for t in traces:
        if t["split"] != "test":
            continue
        for rank, h in enumerate(t["hits"], 1):
            rows.append({"strategy": t["strategy"], "id": t["id"], "rank": rank, "chunk_id": h["chunk_id"],
                         "document_id": h["document_id"], "source": h["source"], "page": h["page"],
                         "pages": h["pages"], "year": h["year"], "chuong": h["chuong"],
                         "dieu_title": h["metadata"].get("dieu_title"),
                         "question_filter": json.dumps(t["question_filter"]) if t["question_filter"] else "",
                         "filter_ok": h["filter_ok"], "text_head": h["text"][:160],
                         "metadata_correct_complete": "", "note": ""})
    _write_csv(audit / "metadata_sheet.csv", rows)
    # 3) Grounding: test question x strategy, top-3 joined.
    rows = []
    for t in traces:
        if t["split"] != "test":
            continue
        top3 = "\n---\n".join(f"[{i}] {h['document_id']} Điều {h['page']}: {h['text']}" for i, h in enumerate(t["hits"], 1))
        rows.append({"strategy": t["strategy"], "id": t["id"], "question": t["question"],
                     "expected_answer": t["expected_answer"], "evidence_hit3_auto": t["hit3"],
                     "top3": top3, "grounding_0_2": "", "reason": ""})
    _write_csv(audit / "grounding_sheet.csv", rows)


def _write_csv(path: Path, rows: list[dict]) -> None:
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default=os.getenv("EMBEDDING_MODEL") or "intfloat/multilingual-e5-base")
    parser.add_argument("--rebuild", action="store_true",
                        help="delete existing rows first so embedding time reflects a full build")
    args = parser.parse_args()
    load_dotenv(STARTER / ".env")
    RESULTS.mkdir(exist_ok=True)
    started = datetime.now(timezone.utc).isoformat()

    log: list[dict] = []
    t0 = time.perf_counter()
    docs = ingest(log)
    t_ingest = time.perf_counter() - t0
    manifest = write_manifest(docs)
    dump(RESULTS / "ingest_log.json", log)
    questions = json.loads((ROOT / "benchmark" / "questions.json").read_text(encoding="utf-8"))
    validate_benchmark(questions, docs)
    print(f"Corpus: {manifest['totals']} | benchmark OK ({len(questions)} câu)")

    chunks = build_chunks(docs)
    embedder = E5Embedder(args.model)
    stats = {s: chunk_stats(c, embedder.count_tokens([x.text for x in c]), embedder.max_seq_length)
             for s, c in chunks.items()}

    store = PgVectorStore(os.environ["DATABASE_URL"], embedder.dimensions)
    store.create_schema()
    if args.rebuild:
        for s in chunks:
            store.upsert(s, [], [], document_ids=[c["source_id"] for c in CORPUS], keep_ids=[])
    timing = {s: index_strategy(store, embedder, s, c) for s, c in chunks.items()}
    # Re-ingest the same version: nothing should be re-embedded and counts must not change.
    reingest = {s: index_strategy(store, embedder, s, c) for s, c in chunks.items()}
    counts = {s: store.count(s) for s in chunks}
    for s, c in chunks.items():
        if counts[s] != len(c):
            raise RuntimeError(f"index {s}: {counts[s]} rows but {len(c)} chunks")
    print("Index:", counts, "| re-ingest embedded:", {s: r["embedded"] for s, r in reingest.items()})

    traces = run_queries(store, embedder, questions)
    summary = summarize(traces)
    import importlib.metadata as md
    run_info = {
        "started_at_utc": started, "python": platform.python_version(), "platform": platform.platform(),
        "embedding": {"provider": "local sentence-transformers", "model": embedder.model_name,
                      "dimensions": embedder.dimensions, "max_seq_length": embedder.max_seq_length,
                      "device": embedder.device, "query_prefix": "query: ", "document_prefix": "passage: ",
                      "normalized": True},
        "vector_store": {"backend": "PostgreSQL 16 + pgvector 0.8.7 (Docker)", "table": store.table,
                         "metric": "cosine (<=>)", "search": "exact (sequential scan, no ANN index)"},
        "packages": {p: md.version(p) for p in ("sentence-transformers", "torch", "transformers",
                                                  "psycopg", "pgvector", "beautifulsoup4", "numpy")},
        "strategies": STRATEGIES, "chunk_params": {"A": CHUNK_A, "B": CHUNK_B}, "top_k": TOP_K,
        "cost_usd": 0, "ingest_parse_seconds": round(t_ingest, 2),
        "index_timing": timing, "reingest_check": reingest, "row_counts": counts, "chunk_stats": stats,
    }
    dump(RESULTS / "run_info.json", run_info)
    dump(RESULTS / "summary.json", summary)
    write_summary_md(summary, stats, timing)
    write_audit_sheets(traces, chunks, docs)
    print((RESULTS / "summary.md").read_text(encoding="utf-8"))


if __name__ == "__main__":
    main()
