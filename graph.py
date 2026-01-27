import argparse
import json
import os
import re
from datetime import datetime, timezone
from typing import TypedDict

from elasticsearch import Elasticsearch
from langgraph.graph import END, START, StateGraph

from config import Config
from llm_summary import summarize_report
from main import build_clusters, build_time_range, fetch_logs, summarize, write_report
from patch_proposal import propose_patch
from sandbox_apply import apply_null_check_guard
from test_runner import run_tests
from pr_creator import create_pr_flow


class AgentState(TypedDict, total=False):
    args: dict
    report: dict
    report_path: str
    summary_text: str
    summary_error: str
    proposal_text: str
    proposal_error: str
    decision: dict
    apply_result: dict
    test_result: dict
    pr_result: dict


def _now_iso():
    return datetime.now(timezone.utc).isoformat()


def _extract_json(text):
    if not text:
        return None
    match = re.search(r"```json\s*(\{.*\})\s*```", text, re.DOTALL)
    if match:
        text = match.group(1)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return {"raw": text}


def _rank(level):
    order = {"low": 0, "medium": 1, "high": 2}
    return order.get(level, 0)


def _decision_from_proposal(proposal, config):
    if not proposal or "proposal" not in proposal:
        return {"approved": False, "reason": "no_proposal"}
    data = proposal["proposal"]
    if isinstance(data, dict) and "raw" in data:
        data = _extract_json(data["raw"])
    if not isinstance(data, dict):
        return {"approved": False, "reason": "invalid_proposal"}
    risk = (data.get("risk") or "low").lower()
    confidence = (data.get("confidence") or "low").lower()
    approved = _rank(confidence) >= _rank(config.decision_min_confidence) and _rank(risk) <= _rank(
        config.decision_max_risk
    )
    return {
        "approved": approved,
        "risk": risk,
        "confidence": confidence,
        "selected_template_id": data.get("selected_template_id"),
        "target_files": data.get("target_files", []),
        "reason": "meets_thresholds" if approved else "below_thresholds",
    }


def ingest_node(state):
    args = state["args"]
    es = Elasticsearch(args["es_hosts"].split(","))
    start_ts, end_ts = build_time_range(args["lookback_minutes"])
    docs = fetch_logs(es, args["index_pattern"], start_ts, end_ts, args["size"])
    clusters = build_clusters(docs)
    report = summarize(docs, clusters)
    report_path = write_report(args["output_dir"], report)
    print(f"Fetched {len(docs)} events from {start_ts} to {end_ts}")
    print(f"Top clusters: {min(len(clusters), 10)}")
    print(f"Report written to {report_path}")
    return {"report": report, "report_path": report_path}


def summary_node(state):
    report = state["report"]
    summary_text, summary_error = summarize_report(report, Config)
    if summary_error:
        print(f"LLM summary skipped: {summary_error}")
    else:
        print("LLM summary generated (not written to file)")
    return {"summary_text": summary_text, "summary_error": summary_error}


def proposal_node(state):
    report = state["report"]
    proposal_text, proposal_error = propose_patch(report, Config)
    if proposal_error:
        print(f"Patch proposal skipped: {proposal_error}")
    else:
        print("Patch proposal generated (not written to file)")
    return {"proposal_text": proposal_text, "proposal_error": proposal_error}


def decide_node(state):
    proposal = {"proposal": _extract_json(state.get("proposal_text"))}
    if state.get("proposal_error"):
        decision = {"approved": False, "reason": state["proposal_error"]}
    else:
        decision = _decision_from_proposal(proposal, Config)
    decision["generated_at"] = _now_iso()
    return {"decision": decision}


def apply_node(state):
    decision = state.get("decision", {})
    if not decision.get("approved"):
        print("Apply skipped: decision not approved")
        return {"apply_result": {"applied": False, "reason": "not_approved", "applied_to_repo": False}}

    if decision.get("selected_template_id") != "null-check-guard":
        print("Apply skipped: template not supported in sandbox")
        return {"apply_result": {"applied": False, "reason": "unsupported_template", "applied_to_repo": False}}

    source_path = os.path.join(
        Config.target_repo_path, "src", "main", "java", "com", "example", "authservice", "UserService.java"
    )
    result, error = apply_null_check_guard(source_path, Config.sandbox_dir)
    if error:
        print(f"Apply skipped: {error}")
        return {"apply_result": {"applied": False, "reason": error, "applied_to_repo": False}}

    print(f"Sandbox patch written to {result['sandbox_path']}")
    print(f"Sandbox diff written to {result['diff_path']}")
    if Config.apply_to_repo:
        with open(result["sandbox_path"], "r", encoding="utf-8") as handle:
            updated = handle.read()
        with open(source_path, "w", encoding="utf-8") as handle:
            handle.write(updated)
        print(f"Applied patch to repo file: {source_path}")
        return {"apply_result": {"applied": True, "applied_to_repo": True, **result}}

    return {"apply_result": {"applied": True, "applied_to_repo": False, **result}}


def test_node(state):
    apply_result = state.get("apply_result", {})
    if not apply_result.get("applied_to_repo"):
        print("Tests skipped: patch not applied to repo")
        return {"test_result": {"skipped": True, "reason": "not_applied_to_repo"}}

    result = run_tests(Config.test_command, Config.target_repo_path)
    if result["exit_code"] == 0:
        print("Tests passed")
    else:
        print("Tests failed")
    return {"test_result": result}


def finalize_node(state):
    decision = state.get("decision", {})
    decision["test_result"] = state.get("test_result")
    decision["pr_result"] = state.get("pr_result")
    output_dir = Config.proposal_output_dir
    os.makedirs(output_dir, exist_ok=True)
    path = os.path.join(output_dir, f"decision-{datetime.now().strftime('%Y%m%d-%H%M%S')}.json")
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(decision, handle, indent=2)
    print(f"Decision written to {path}")
    return {}


def pr_node(state):
    decision = state.get("decision", {})
    apply_result = state.get("apply_result", {})
    test_result = state.get("test_result", {})
    pr_result = create_pr_flow(Config, decision, apply_result, test_result)
    if pr_result.get("created"):
        print(f"PR created: {pr_result.get('url')}")
    else:
        print(f"PR skipped: {pr_result.get('reason')}")
    return {"pr_result": pr_result}


def build_graph():
    graph = StateGraph(AgentState)
    graph.add_node("ingest", ingest_node)
    graph.add_node("summarize", summary_node)
    graph.add_node("propose", proposal_node)
    graph.add_node("decide", decide_node)
    graph.add_node("apply", apply_node)
    graph.add_node("test", test_node)
    graph.add_node("pr", pr_node)
    graph.add_node("finalize", finalize_node)
    graph.add_edge(START, "ingest")
    graph.add_edge("ingest", "summarize")
    graph.add_edge("summarize", "propose")
    graph.add_edge("propose", "decide")
    graph.add_edge("decide", "apply")
    graph.add_edge("apply", "test")
    graph.add_edge("test", "pr")
    graph.add_edge("pr", "finalize")
    graph.add_edge("finalize", END)
    return graph.compile()


def main():
    parser = argparse.ArgumentParser(description="LangGraph agent loop (suggest-only)")
    parser.add_argument("--es-hosts", default=",".join(Config.es_hosts))
    parser.add_argument("--index-pattern", default=Config.index_pattern)
    parser.add_argument("--lookback-minutes", type=int, default=Config.lookback_minutes)
    parser.add_argument("--size", type=int, default=Config.query_size)
    parser.add_argument("--output-dir", default=Config.output_dir)
    args = parser.parse_args()

    app = build_graph()
    app.invoke(
        {
            "args": {
                "es_hosts": args.es_hosts,
                "index_pattern": args.index_pattern,
                "lookback_minutes": args.lookback_minutes,
                "size": args.size,
                "output_dir": args.output_dir,
            }
        }
    )


if __name__ == "__main__":
    main()
