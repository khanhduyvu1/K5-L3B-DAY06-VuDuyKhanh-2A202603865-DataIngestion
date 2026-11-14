"""Evaluate retrieved evidence and preserve per-query traces.

A retrieved chunk is an *evidence hit* when it belongs to a gold source/article
and contains the **whole** gold evidence (all quotes, after normalising case and
whitespace). Coherence and grounding labels are manual and are not inferred here.
"""
from __future__ import annotations

import re
import unicodedata
from collections import defaultdict
from typing import Any


def norm(text: str) -> str:
    text = unicodedata.normalize("NFC", text).lower()
    return re.sub(r"\s+", " ", text).strip()


def gold_list(question: dict[str, Any]) -> list[dict[str, Any]]:
    golds = [{"source_id": question["gold_source_id"], "page": question["gold_page"],
              "evidence_quote": question["evidence_quote"]}]
    golds += question.get("alt_gold", [])
    for g in golds:
        q = g["evidence_quote"]
        g["quotes"] = [q] if isinstance(q, str) else list(q)
    return golds


def check_hit(golds: list[dict[str, Any]], hit: dict[str, Any]) -> dict[str, Any]:
    text = norm(hit["text"])
    page_match, evidence_full = False, False
    for g in golds:
        if hit["document_id"] == g["source_id"] and g["page"] in hit["pages"]:
            page_match = True
            if all(norm(q) in text for q in g["quotes"]):
                evidence_full = True
    return {"page_match": page_match, "evidence_hit": evidence_full}


def filter_ok(filters: dict[str, Any] | None, hit: dict[str, Any]) -> bool | None:
    if not filters:
        return None
    return all(hit.get(k) == v for k, v in filters.items())


def evaluate_query(question: dict[str, Any], hits: list[dict[str, Any]],
                   applied_filter: dict[str, Any] | None = None) -> dict[str, Any]:
    golds = gold_list(question)
    flags = [check_hit(golds, h) for h in hits]
    evidence = [f["evidence_hit"] for f in flags]
    first_rank = next((i + 1 for i, e in enumerate(evidence) if e), None)
    page_only = any(f["page_match"] and not f["evidence_hit"] for f in flags) and not any(evidence)
    # Filter compliance is judged against the question's filter even when the
    # strategy did not apply it (A/B), so the effect of filtering is visible.
    qfilter = question.get("filter")
    compliance = [filter_ok(qfilter, h) for h in hits] if qfilter else []
    return {
        "hit1": bool(evidence[:1] and evidence[0]),
        "hit3": any(evidence[:3]),
        "first_hit_rank": first_rank,
        "error": None if any(evidence[:3]) else ("evidence_split_or_partial" if page_only else "wrong_article"),
        "filter_applied": applied_filter,
        "filter_compliant_top3": (all(compliance[:3]) if qfilter else None),
        "hits": [{**h, **f, "filter_ok": filter_ok(qfilter, h)} for h, f in zip(hits, flags)],
    }


def summarize(traces: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate Hit@1 / Evidence Hit@3 and filter compliance by strategy and split."""
    out: dict[str, Any] = defaultdict(dict)
    groups: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for t in traces:
        groups[(t["strategy"], t["split"])].append(t)
        groups[(t["strategy"], "all")].append(t)
    for (strategy, split), items in sorted(groups.items()):
        with_filter = [t for t in items if t["filter_compliant_top3"] is not None]
        out[strategy][split] = {
            "n": len(items),
            "hit1": sum(t["hit1"] for t in items),
            "hit3": sum(t["hit3"] for t in items),
            "filter_questions": len(with_filter),
            "filter_compliant": sum(t["filter_compliant_top3"] for t in with_filter),
            "misses": [t["id"] for t in items if not t["hit3"]],
        }
    return dict(out)
