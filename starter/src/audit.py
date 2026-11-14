"""Audit helpers, run after src.run:  python -m src.audit

1. Metadata check (test questions x top-3 x strategy): compares every stored
   field with the parsed source, so the check is reproducible.
2. Aggregates the manual coherence / grounding label files.
"""
from __future__ import annotations

import csv
import json
from collections import Counter

from .evaluation import norm
from .run import RESULTS, ingest

AUDIT = RESULTS / "audit"


def metadata_audit() -> dict:
    docs = ingest([])
    by_key = {(d, p.page): p for d, pages in docs.items() for p in pages}
    stream = {d: norm(" ".join(p.text for p in pages)) for d, pages in docs.items()}
    year_of = {d: pages[0].metadata["year"] for d, pages in docs.items()}
    url_of = {d: pages[0].source for d, pages in docs.items()}

    rows, totals = [], Counter()
    traces = [json.loads(line) for line in (RESULTS / "traces.jsonl").open(encoding="utf-8")]
    for t in traces:
        if t["split"] != "test":
            continue
        for rank, h in enumerate(t["hits"], 1):
            problems = []
            first = by_key.get((h["document_id"], h["page"]))
            if first is None:
                problems.append("page không tồn tại trong nguồn")
            else:
                if h["year"] != year_of[h["document_id"]]:
                    problems.append("year sai")
                if h["chuong"] != first.metadata["chuong"]:
                    problems.append("chuong sai")
                if h["metadata"].get("dieu_title") != first.metadata["dieu_title"]:
                    problems.append("dieu_title sai")
            if h["source"] != url_of.get(h["document_id"]):
                problems.append("source sai")
            if h["page"] not in h["pages"]:
                problems.append("page không thuộc pages")
            # Every line must come from the cited articles (B repeats the heading and
            # a truncated clause intro ending in "…", so check line by line).
            covered = norm(" ".join(by_key[(h["document_id"], p)].text for p in h["pages"]
                                    if (h["document_id"], p) in by_key))
            lines = [norm(x.rstrip("…")) for x in h["text"].split("\n") if x.strip()]
            if not all(x in covered for x in lines):
                in_doc = all(x in stream[h["document_id"]] for x in lines)
                problems.append("pages thiếu Điều" if in_doc else "text không khớp nguồn")
            note = ""
            if len(h["pages"]) > 1:
                note = f"chunk trải {len(h['pages'])} Điều {h['pages']}; trường page chỉ ghi Điều đầu"
            ok = not problems
            totals[(t["strategy"], ok)] += 1
            rows.append({"strategy": t["strategy"], "id": t["id"], "rank": rank, "chunk_id": h["chunk_id"],
                         "document_id": h["document_id"], "page": h["page"], "pages": h["pages"],
                         "year": h["year"], "chuong": h["chuong"],
                         "question_filter": json.dumps(t["question_filter"]) if t["question_filter"] else "",
                         "filter_ok": h["filter_ok"], "metadata_correct_complete": ok,
                         "problems": "; ".join(problems), "note": note})
    with (AUDIT / "metadata_labels.csv").open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    out = {}
    for s in sorted({r["strategy"] for r in rows}):
        n = sum(1 for r in rows if r["strategy"] == s)
        multi = sum(1 for r in rows if r["strategy"] == s and r["note"])
        out[s] = {"correct_complete": totals[(s, True)], "checked": n, "multi_article_records": multi}
    return out


def manual_summary() -> dict:
    out = {}
    for name, col in (("coherence", "score_0_2"), ("grounding", "grounding_0_2")):
        rows = list(csv.DictReader((AUDIT / f"{name}_labels.csv").open(encoding="utf-8")))
        for s in sorted({r["strategy"] for r in rows}):
            scores = [int(r[col]) for r in rows if r["strategy"] == s]
            out.setdefault(s, {})[name] = {"n": len(scores), "mean_of_2": round(sum(scores) / len(scores), 2),
                                          "dist_0_1_2": [scores.count(k) for k in (0, 1, 2)]}
    return out


def main() -> None:
    meta = metadata_audit()
    manual = manual_summary()
    summary = json.loads((RESULTS / "summary.json").read_text(encoding="utf-8"))
    combined = {s: {**manual.get(s, {}), "metadata": meta.get(s),
                    "filter_compliance_test": f"{summary[s]['test']['filter_compliant']}/{summary[s]['test']['filter_questions']}",
                    "filter_compliance_dev": f"{summary[s]['dev']['filter_compliant']}/{summary[s]['dev']['filter_questions']}"}
                for s in ("A", "B", "C")}
    (RESULTS / "manual_summary.json").write_text(json.dumps(combined, ensure_ascii=False, indent=2), encoding="utf-8")
    lines = ["# Kết quả audit thủ công + metadata", "",
             "Nhãn coherence/grounding: Claude chấm nháp, tác giả (Vũ Duy Khánh) đã duyệt toàn bộ (xem cột annotator).", "",
             "| Strategy | Coherence TB /2 (n) | Phân bố coherence 0/1/2 | Metadata đủ & đúng (n/N) | Filter tuân thủ test | Filter tuân thủ dev | Grounding 0/1/2 | Grounding TB /2 |",
             "|---|---|---|---|---|---|---|---|"]
    for s, r in combined.items():
        c, g, m = r["coherence"], r["grounding"], r["metadata"]
        lines.append(f"| {s} | {c['mean_of_2']} ({c['n']}) | {'/'.join(map(str, c['dist_0_1_2']))} | "
                     f"{m['correct_complete']}/{m['checked']} | {r['filter_compliance_test']} | {r['filter_compliance_dev']} | "
                     f"{'/'.join(map(str, g['dist_0_1_2']))} | {g['mean_of_2']} |")
    (RESULTS / "manual_summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))
    print(json.dumps(meta, ensure_ascii=False))


if __name__ == "__main__":
    main()
