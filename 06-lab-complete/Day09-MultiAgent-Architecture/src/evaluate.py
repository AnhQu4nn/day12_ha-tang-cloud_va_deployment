"""
Batch evaluator for the ShoppingAssistant pipeline.

Evaluates each test case against:
  1. route_correct  — did the supervisor route to the expected workers?
  2. status_correct — does the final answer contain the expected status keyword?
  3. has_evidence   — does the final answer have an Evidence section?
  4. contains_check — do expected keywords appear in the answer?
"""
from __future__ import annotations

import json
import re
import sys
import time
from pathlib import Path

# ── make sure src/ is on PYTHONPATH when run directly ──────────────────────
_src = Path(__file__).resolve().parent
if str(_src) not in sys.path:
    sys.path.insert(0, str(_src))

from app.graph import ShoppingAssistant


# ───────────────────────────────────────────────────────────────────────────
# Scoring helpers
# ───────────────────────────────────────────────────────────────────────────

PASS = "✅ PASS"
FAIL = "❌ FAIL"
SKIP = "⚪ SKIP"


def check_route(result: dict, expected: list[str]) -> tuple[str, str]:
    """Return (verdict, detail)."""
    if not expected:
        return SKIP, "no expected_route"
    route = result.get("route") or {}
    actual = []
    if route.get("needs_policy"):
        actual.append("policy")
    if route.get("needs_data"):
        actual.append("data")

    expected_set = set(expected)
    actual_set = set(actual)
    ok = expected_set == actual_set or expected_set.issubset(actual_set)
    return (PASS if ok else FAIL), f"expected={sorted(expected_set)}  actual={sorted(actual_set)}"


def check_status(result: dict, expected_status: str) -> tuple[str, str]:
    """Scan route + worker statuses for the expected status keyword."""
    if not expected_status:
        return SKIP, "no expected_status"

    answer = (result.get("final_answer") or "").lower()
    route  = result.get("route") or {}

    # 1) supervisor already said clarification_needed → routed to response immediately
    if expected_status == "clarification_needed":
        ok = (
            route.get("status") == "clarification_needed"
            or "clarification_needed" in answer
            or "clarification" in answer
            or "cần thêm thông tin" in answer
            or "vui lòng cung cấp" in answer
        )
        return (PASS if ok else FAIL), f"expected={expected_status}"

    if expected_status == "not_found":
        ok = (
            (result.get("data_result") or {}).get("status") == "not_found"
            or "not_found" in answer
            or "không tìm thấy" in answer
        )
        return (PASS if ok else FAIL), f"expected={expected_status}"

    if expected_status == "ok":
        ok = (
            (result.get("policy_result") or {}).get("status") == "ok"
            or (result.get("data_result") or {}).get("status") == "ok"
            or "answer:" in answer
            or "evidence:" in answer
        )
        return (PASS if ok else FAIL), f"expected={expected_status}"

    return SKIP, f"unknown expected_status={expected_status}"


def check_evidence(result: dict) -> tuple[str, str]:
    """Check if the final answer has some evidence section."""
    answer = result.get("final_answer") or ""
    has = bool(re.search(r"evidence:|policy:|order data:|nguồn:|trích dẫn:", answer, re.IGNORECASE))
    return (PASS if has else FAIL), "evidence section present" if has else "no evidence section found"


def check_contains(result: dict, keywords: list[str]) -> tuple[str, str]:
    """Return PASS only if ALL expected keywords appear in the final answer."""
    if not keywords:
        return SKIP, "no expected_contains"
    answer = (result.get("final_answer") or "").lower()
    missing = [kw for kw in keywords if kw.lower() not in answer]
    ok = len(missing) == 0
    detail = "all keywords present" if ok else f"missing: {missing}"
    return (PASS if ok else FAIL), detail


# ───────────────────────────────────────────────────────────────────────────
# Main evaluation loop
# ───────────────────────────────────────────────────────────────────────────

def run_eval(
    test_file: Path,
    output_dir: Path,
    test_filter: list[str] | None = None,
) -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    with open(test_file, encoding="utf-8") as f:
        test_cases = json.load(f)

    if test_filter:
        test_cases = [tc for tc in test_cases if tc.get("id") in test_filter]

    output_dir.mkdir(parents=True, exist_ok=True)

    assistant = ShoppingAssistant()

    summary_rows = []
    total = len(test_cases)
    passed = 0

    for i, tc in enumerate(test_cases, 1):
        qid      = tc.get("id", f"Q{i:02d}")
        question = tc.get("question", "")
        exp_route    = tc.get("expected_route", [])
        exp_status   = tc.get("expected_status", "")
        exp_contains = tc.get("expected_contains", [])

        print(f"\n{'─'*60}")
        print(f"[{i}/{total}] {qid}: {question}")
        print(f"{'─'*60}")

        trace_file = output_dir / f"trace_{qid}.json"
        t0 = time.time()
        try:
            result = assistant.ask(question, trace_file=trace_file)
            err = None
        except Exception as exc:
            print(f"  ⚠️  Exception: {exc}")
            result = {}
            err = str(exc)
        elapsed = round(time.time() - t0, 2)

        # ── Scoring ────────────────────────────────────────────
        route_v,    route_d    = check_route(result, exp_route)
        status_v,   status_d   = check_status(result, exp_status)
        evidence_v, evidence_d = check_evidence(result)
        contains_v, contains_d = check_contains(result, exp_contains)

        all_ok = all(
            v in (PASS, SKIP)
            for v in [route_v, status_v, evidence_v, contains_v]
        )
        if all_ok:
            passed += 1

        # ── Print per-case result ─────────────────────────────
        print(f"  route_correct  : {route_v}   ({route_d})")
        print(f"  status_correct : {status_v}  ({status_d})")
        print(f"  has_evidence   : {evidence_v}  ({evidence_d})")
        print(f"  contains_check : {contains_v}  ({contains_d})")
        print(f"  ⏱  {elapsed}s")

        answer_snippet = (result.get("final_answer") or "")[:200].replace("\n", " ")
        print(f"  💬  {answer_snippet}…")

        row = {
            "id": qid,
            "question": question,
            "elapsed_s": elapsed,
            "error": err,
            "route_correct": route_v,
            "route_detail": route_d,
            "status_correct": status_v,
            "status_detail": status_d,
            "has_evidence": evidence_v,
            "evidence_detail": evidence_d,
            "contains_check": contains_v,
            "contains_detail": contains_d,
            "overall": PASS if all_ok else FAIL,
            "final_answer_snippet": answer_snippet,
            "trace_file": str(trace_file),
        }
        summary_rows.append(row)

    # ── Write summary JSON ────────────────────────────────────
    summary_path = output_dir / "summary.json"
    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump(summary_rows, f, ensure_ascii=False, indent=2)

    # ── Print final score table ───────────────────────────────
    print(f"\n{'═'*60}")
    print(f"  BATCH EVALUATION COMPLETE")
    print(f"  Passed : {passed}/{total}  ({100*passed//total}%)")
    print(f"  Output : {output_dir}/")
    print(f"{'═'*60}")
    print(f"\n{'ID':<6} {'Route':^10} {'Status':^10} {'Evidence':^10} {'Contains':^10} {'Overall':^10}")
    print("─" * 58)
    for row in summary_rows:
        icon = lambda v: "✅" if v == PASS else ("⚪" if v == SKIP else "❌")
        print(f"{row['id']:<6} {icon(row['route_correct']):^10} {icon(row['status_correct']):^10}"
              f" {icon(row['has_evidence']):^10} {icon(row['contains_check']):^10}"
              f" {icon(row['overall']):^10}")
    print()


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--test-file", default="../data/test.json")
    p.add_argument("--output-dir", default="artifacts/batch")
    p.add_argument("--filter", nargs="*", help="Only run these question IDs, e.g. Q01 Q05")
    args = p.parse_args()

    run_eval(
        test_file=Path(args.test_file),
        output_dir=Path(args.output_dir),
        test_filter=args.filter,
    )
