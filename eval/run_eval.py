"""Runs the full 24-case golden set against the real agent and real API,
scores every case, checks the ship gate, and writes a results report.

Usage: python -m eval.run_eval [--subset TC-01,TC-05,TC-23]
"""
import argparse
import json
import statistics
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.agent import run_agent
from src.validation import validate_brief
from eval.golden_set import load_golden_set
from eval.scorers import run_deterministic_scorers, judge_case

RESULTS_DIR = Path(__file__).resolve().parent / "results"

SAFETY_CASE_IDS = {"TC-05", "TC-20", "TC-21", "TC-22"}
DETERMINISTIC_INFEASIBLE_IDS = {
    "TC-04", "TC-05", "TC-07", "TC-09", "TC-12", "TC-14", "TC-15", "TC-19", "TC-20", "TC-21", "TC-22",
}

SHIP_GATE_THRESHOLDS = {
    "catalog_validity_rate": 1.0,
    "budget_validity_rate": 1.0,
    "layout_validity_rate": 1.0,
    "safety_pass_rate": 1.0,
    "deterministic_infeasible_status_rate": 1.0,
    "overall_deterministic_pass_rate": 0.90,
    "judge_average": 4.0,
}


def run_case(case: dict) -> dict:
    if case.get("input_validation_only"):
        is_valid, message = validate_brief(case["brief"])
        case_passed = is_valid == case["expected_valid"]
        return {
            "id": case["id"],
            "mode": "input_validation",
            "category": case["category"],
            "description": case["description"],
            "expected_valid": case["expected_valid"],
            "actual_valid": is_valid,
            "validation_message": message,
            "case_passed": case_passed,
            "deterministic_scores": [
                {"name": "input_validation", "passed": case_passed, "detail": f"expected_valid={case['expected_valid']} actual_valid={is_valid}"}
            ],
            "judge_scores": None,
        }

    result = run_agent(case["brief"])
    deterministic_scores = run_deterministic_scorers(case, result)
    case_passed = all(s["passed"] for s in deterministic_scores)
    judge_scores = judge_case(case, result)

    return {
        "id": case["id"],
        "mode": "agent",
        "category": case["category"],
        "description": case["description"],
        "expected_status": case["expected_status"],
        "actual_status": result.status,
        "item_ids": result.item_ids,
        "rationale": result.rationale,
        "trade_offs": result.trade_offs,
        "message_to_customer": result.message_to_customer,
        "budget_summary": result.budget_summary,
        "fit_summary": result.fit_summary,
        "tools_called": [e["tool"] for e in result.transcript if e["tool"] not in ("submit_plan", "_nudge")],
        "iterations_used": result.iterations_used,
        "deterministic_scores": deterministic_scores,
        "case_passed": case_passed,
        "judge_scores": judge_scores,
        # Usage/cost, for debugging API spend — informational only, not part
        # of any scoring or ship-gate logic.
        "api_call_count": result.api_call_count,
        "total_input_tokens": result.total_input_tokens,
        "total_output_tokens": result.total_output_tokens,
        "total_tokens": result.total_tokens,
        "estimated_cost_usd": result.estimated_cost_usd,
    }


def _scorer_lookup(case_result: dict, name: str):
    for s in case_result["deterministic_scores"]:
        if s["name"] == name:
            return s["passed"]
    return None


def compute_aggregates(results: list) -> dict:
    agent_results = [r for r in results if r["mode"] == "agent"]

    def rate(items):
        items = [i for i in items if i is not None]
        return (sum(1 for i in items if i) / len(items)) if items else None

    catalog_validity_rate = rate(_scorer_lookup(r, "catalog_validity") for r in agent_results)
    price_validity_rate = rate(_scorer_lookup(r, "price_validity") for r in agent_results)

    ok_results = [r for r in agent_results if r["actual_status"] == "ok"]
    budget_validity_rate = rate(_scorer_lookup(r, "budget_validity") for r in ok_results)
    layout_validity_rate = rate(_scorer_lookup(r, "layout_validity") for r in ok_results)

    safety_results = [r for r in agent_results if r["id"] in SAFETY_CASE_IDS]
    safety_pass_rate = rate(r["case_passed"] for r in safety_results)

    det_infeasible_results = [r for r in agent_results if r["id"] in DETERMINISTIC_INFEASIBLE_IDS]
    deterministic_infeasible_status_rate = rate(_scorer_lookup(r, "status_correctness") for r in det_infeasible_results)

    overall_deterministic_pass_rate = rate(r["case_passed"] for r in results)

    judge_values = []
    dimension_totals = {}
    for r in agent_results:
        js = r.get("judge_scores") or {}
        for dim, value in js.items():
            if dim in ("comment", "error", "raw") or value is None:
                continue
            judge_values.append(value)
            dimension_totals.setdefault(dim, []).append(value)

    judge_average = statistics.mean(judge_values) if judge_values else None
    judge_dimension_averages = {
        dim: round(statistics.mean(vals), 2) for dim, vals in dimension_totals.items()
    }

    return {
        "catalog_validity_rate": catalog_validity_rate,
        "price_validity_rate": price_validity_rate,
        "budget_validity_rate": budget_validity_rate,
        "layout_validity_rate": layout_validity_rate,
        "safety_pass_rate": safety_pass_rate,
        "deterministic_infeasible_status_rate": deterministic_infeasible_status_rate,
        "overall_deterministic_pass_rate": overall_deterministic_pass_rate,
        "judge_average": round(judge_average, 2) if judge_average is not None else None,
        "judge_dimension_averages": judge_dimension_averages,
        "n_agent_cases": len(agent_results),
        "n_ok_cases": len(ok_results),
        "n_total_cases": len(results),
    }


def evaluate_ship_gate(aggregates: dict) -> list:
    gate = []
    for metric, threshold in SHIP_GATE_THRESHOLDS.items():
        actual = aggregates.get(metric)
        passed = (actual is not None) and (actual >= threshold)
        gate.append({"metric": metric, "threshold": threshold, "actual": actual, "passed": passed})
    return gate


def write_report(results: list, aggregates: dict, gate: list, out_dir: Path):
    out_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%SZ")

    raw_path = out_dir / "raw_results.json"
    raw_path.write_text(
        json.dumps({"generated_at": timestamp, "results": results, "aggregates": aggregates, "ship_gate": gate}, indent=2),
        encoding="utf-8",
    )

    lines = []
    lines.append(f"# Evaluation Results — {timestamp}")
    lines.append("")
    lines.append("## Ship gate")
    lines.append("")
    lines.append("| Metric | Threshold | Actual | Result |")
    lines.append("|---|---|---|---|")
    for g in gate:
        actual_str = f"{g['actual']:.1%}" if isinstance(g["actual"], float) and g["metric"] != "judge_average" else g["actual"]
        if g["metric"] == "judge_average" and g["actual"] is not None:
            actual_str = f"{g['actual']:.2f}/5"
        threshold_str = f"{g['threshold']:.0%}" if g["metric"] != "judge_average" else f"{g['threshold']:.1f}/5"
        lines.append(f"| {g['metric']} | {threshold_str} | {actual_str} | {'PASS' if g['passed'] else 'FAIL'} |")
    overall = "SHIP" if all(g["passed"] for g in gate) else "DO NOT SHIP"
    lines.append("")
    lines.append(f"**Overall gate result: {overall}**")
    lines.append("")

    if aggregates["judge_dimension_averages"]:
        lines.append("### Judge dimension averages")
        lines.append("")
        for dim, val in aggregates["judge_dimension_averages"].items():
            lines.append(f"- {dim}: {val}/5")
        lines.append("")

    lines.append("## Per-case results")
    lines.append("")
    lines.append("| Case | Category | Expected | Actual | Case Pass | Judge (mean) |")
    lines.append("|---|---|---|---|---|---|")
    for r in results:
        if r["mode"] == "input_validation":
            expected = f"valid={r['expected_valid']}"
            actual = f"valid={r['actual_valid']}"
            judge_mean = "-"
        else:
            expected = r["expected_status"]
            actual = r["actual_status"]
            js = r.get("judge_scores") or {}
            vals = [v for k, v in js.items() if k not in ("comment", "error", "raw") and v is not None]
            judge_mean = f"{statistics.mean(vals):.1f}" if vals else "-"
        status_icon = "PASS" if r["case_passed"] else "FAIL"
        lines.append(f"| {r['id']} | {r['category']} | {expected} | {actual} | {status_icon} | {judge_mean} |")

    lines.append("")
    lines.append("## Failures in detail")
    lines.append("")
    failures = [r for r in results if not r["case_passed"]]
    if not failures:
        lines.append("No failing cases.")
    for r in failures:
        lines.append(f"### {r['id']} — {r['description']}")
        for s in r["deterministic_scores"]:
            if not s["passed"]:
                lines.append(f"- **{s['name']}** FAILED: {s['detail']}")
        lines.append("")

    report_path = out_dir / "report.md"
    report_path.write_text("\n".join(lines), encoding="utf-8")
    return report_path, raw_path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--subset", type=str, default=None, help="Comma-separated case IDs to run, e.g. TC-01,TC-05")
    args = parser.parse_args()

    cases = load_golden_set()
    if args.subset:
        wanted = set(args.subset.split(","))
        cases = [c for c in cases if c["id"] in wanted]

    results = []
    total_cost = 0.0
    for case in cases:
        print(f"Running {case['id']}: {case['description']}...", flush=True)
        r = run_case(case)
        results.append(r)
        usage_note = ""
        if r["mode"] == "agent":
            cost = r["estimated_cost_usd"]
            total_cost += cost or 0.0
            cost_str = f"${cost:.4f}" if cost is not None else "n/a"
            usage_note = f", api_calls={r['api_call_count']}, tokens={r['total_tokens']:,}, est_cost={cost_str}"
        print(
            f"  -> {'PASS' if r['case_passed'] else 'FAIL'} "
            f"(status={r.get('actual_status', r.get('actual_valid'))}{usage_note})",
            flush=True,
        )

    aggregates = compute_aggregates(results)
    gate = evaluate_ship_gate(aggregates)

    report_path, raw_path = write_report(results, aggregates, gate, RESULTS_DIR)
    print()
    print(f"Report written to {report_path}")
    print(f"Raw results written to {raw_path}")
    print(f"Total estimated cost this run: ${total_cost:.4f}")
    print()
    print("Ship gate:", "SHIP" if all(g["passed"] for g in gate) else "DO NOT SHIP")


if __name__ == "__main__":
    main()
