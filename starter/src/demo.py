"""Interactive demo: ask a question, see top-3 of A / B / C side by side.

Run from starter/ after `python -m src.run`:
    python -m src.demo                                  # interactive
    python -m src.demo "Làm thêm tối đa mấy giờ một tháng?" --year 2019
    python -m src.demo --id q03                         # replay a benchmark question
"""
from __future__ import annotations

import argparse
import json
import os
import textwrap

from dotenv import load_dotenv

from .embeddings import E5Embedder
from .evaluation import evaluate_query
from .run import ROOT, STARTER, STRATEGIES, TOP_K
from .store import PgVectorStore

BOLD, DIM, GREEN, RED, RESET = "\033[1m", "\033[2m", "\033[32m", "\033[31m", "\033[0m"


def show(store: PgVectorStore, embedder: E5Embedder, question: str, year: int | None,
         bench: dict | None, strategies: list[str]) -> None:
    qv = embedder.embed_query(question)
    print(f"\n{BOLD}❓ {question}{RESET}" + (f"   {DIM}[filter year={year}]{RESET}" if year else ""))
    if bench:
        print(f"{DIM}   Gold: {bench['gold_source_id']} Điều {bench['gold_page']} · đáp án: {bench['expected_answer']}{RESET}")
    for name in strategies:
        cfg = STRATEGIES[name]
        applied = {"year": year} if (cfg["filter"] and year) else None
        hits = store.search(cfg["index"], qv, TOP_K, applied)
        ev = evaluate_query(bench, hits, applied) if bench else None
        tag = ""
        if ev:
            tag = f"  Hit@1={'✅' if ev['hit1'] else '❌'} Hit@3={'✅' if ev['hit3'] else '❌'}"
        print(f"\n{BOLD}── Strategy {name}{RESET} {DIM}({cfg['chunking']}; filter={'year' if applied else 'không'}){RESET}{tag}")
        for i, h in enumerate(hits, 1):
            wrong_year = year and h["year"] != year
            color = RED if wrong_year else GREEN
            mark = ""
            if ev:
                mark = " ✔evidence" if ev["hits"][i - 1]["evidence_hit"] else ""
            pages = ",".join(map(str, h["pages"]))
            print(f"  {i}. {color}BLLĐ {h['year']}{RESET} · Điều {pages} · score {h['score']:.3f}{mark}")
            body = " ".join(h["text"].split())
            print(textwrap.indent(textwrap.fill(body[:320] + ("…" if len(body) > 320 else ""), 100), "     "))


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("question", nargs="?")
    p.add_argument("--year", type=int, choices=[2012, 2019])
    p.add_argument("--id", help="replay a benchmark question, e.g. q03")
    p.add_argument("--strategies", default="ABC")
    args = p.parse_args()
    load_dotenv(STARTER / ".env")

    print(f"{DIM}Đang nạp model…{RESET}")
    embedder = E5Embedder()
    store = PgVectorStore(os.environ["DATABASE_URL"], embedder.dimensions)
    counts = {s: store.count(s) for s in ("A", "B")}
    if not all(counts.values()):
        raise SystemExit(f"Index trống {counts}: chạy `python -m src.run` trước.")
    strategies = [s for s in args.strategies.upper() if s in STRATEGIES]

    bench_by_id = {q["id"]: q for q in json.loads((ROOT / "benchmark" / "questions.json").read_text(encoding="utf-8"))}
    if args.id:
        q = bench_by_id[args.id]
        show(store, embedder, q["question"], (q.get("filter") or {}).get("year"), q, strategies)
        return
    if args.question:
        show(store, embedder, args.question, args.year, None, strategies)
        return
    print(f"Index: A={counts['A']} chunk, B={counts['B']} chunk. Gõ câu hỏi; thêm '@2012' hoặc '@2019' ở cuối để lọc năm; "
          f"'q03' để chạy câu benchmark; Enter trống để thoát.")
    while True:
        try:
            line = input("\n> ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not line:
            break
        if line in bench_by_id:
            q = bench_by_id[line]
            show(store, embedder, q["question"], (q.get("filter") or {}).get("year"), q, strategies)
            continue
        year = None
        for y in (2012, 2019):
            if line.endswith(f"@{y}"):
                year, line = y, line[: -len(f"@{y}")].strip()
        show(store, embedder, line, year, None, strategies)


if __name__ == "__main__":
    main()
