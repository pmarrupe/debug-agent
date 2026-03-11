import argparse
import json
import os
import re
from datetime import datetime, timezone
from typing import TypedDict

from langgraph.graph import END, START, StateGraph

from config import Config
from llm_summary import summarize_report
from main import build_clusters, summarize, write_report
from trino_logs import fetch_logs_from_trino
from patch_proposal import propose_patch
from template_appliers import get_applier, list_templates, resolve_target_paths
from generic_patch import apply_llm_patch
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
    """Extract JSON from text, optionally inside ```json ... ```. Avoids greedy regex (catastrophic backtracking on large LLM output)."""
    if not text:
        return None
    text = text.strip()
    # If wrapped in markdown code block, extract the content without a greedy regex
    if "```json" in text or "```\n{" in text:
        start_marker = "```json"
        idx = text.find(start_marker)
        if idx == -1:
            idx = text.find("```")
            if idx != -1:
                idx += 3
        else:
            idx += len(start_marker)
        # Content starts after optional whitespace/newline
        while idx < len(text) and text[idx] in " \t\n\r":
            idx += 1
        end_idx = text.find("\n```", idx)
        if end_idx == -1:
            end_idx = text.find("```", idx)
        if end_idx >= 0:
            text = text[idx:end_idx].strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return {"raw": text}


def _rank(level):
    order = {"low": 0, "medium": 1, "high": 2}
    return order.get(level, 0)


def _normalize_level(value):
    """Normalize risk/confidence to 'low'|'medium'|'high'; LLM may return int or other types."""
    if value is None:
        return "low"
    s = str(value).strip().lower()
    if s in ("low", "medium", "high"):
        return s
    return "low"


def _parse_proposal_to_fixes(proposal_text):
    """
    Parse raw proposal text and normalize to { fixes: [ ... ] }.
    Supports: (1) JSON with top-level 'fixes' array; (2) legacy single object with selected_template_id + target_files.
    Returns (parsed_dict, error_str). parsed_dict has 'fixes' as list of fix items with selected_template_id, target_files.
    """
    if not proposal_text or not proposal_text.strip():
        return None, "empty_proposal"
    data = _extract_json(proposal_text.strip())
    if isinstance(data, dict) and "raw" in data and list(data.keys()) == ["raw"]:
        try:
            data = json.loads(data["raw"]) if isinstance(data["raw"], str) else data["raw"]
        except (json.JSONDecodeError, TypeError):
            return None, "invalid_json"
    if not isinstance(data, dict):
        return None, "invalid_proposal"
    fixes = data.get("fixes")
    if isinstance(fixes, list) and len(fixes) > 0:
        normalized = []
        for i, f in enumerate(fixes):
            if not isinstance(f, dict):
                continue
            normalized.append({
                "index": i,
                "selected_template_id": f.get("selected_template_id"),
                "target_files": f.get("target_files") if isinstance(f.get("target_files"), list) else [],
                "rationale": f.get("rationale"),
                "risk": _normalize_level(f.get("risk")),
                "confidence": _normalize_level(f.get("confidence")),
                "error_type": f.get("error_type"),
                "cluster_key": f.get("cluster_key"),
                "patch_content": f.get("patch_content") if isinstance(f.get("patch_content"), str) else None,
                "edits": f.get("edits") if isinstance(f.get("edits"), list) else None,
            })
        if not normalized:
            return None, "no_valid_fixes"
        return {"fixes": normalized, "plan_summary": data.get("plan_summary"), "tests": data.get("tests")}, None
    # Legacy: single top-level selected_template_id + target_files
    tid = data.get("selected_template_id")
    tfiles = data.get("target_files")
    if isinstance(tfiles, list):
        tfiles = tfiles
    else:
        tfiles = []
    if tid or tfiles:
        return {
            "fixes": [{
                "index": 0,
                "selected_template_id": tid,
                "target_files": tfiles,
                "rationale": data.get("rationale"),
                "risk": _normalize_level(data.get("risk")),
                "confidence": _normalize_level(data.get("confidence")),
                "error_type": data.get("error_type"),
                "cluster_key": data.get("cluster_key"),
                "patch_content": data.get("patch_content") if isinstance(data.get("patch_content"), str) else None,
                "edits": data.get("edits") if isinstance(data.get("edits"), list) else None,
            }],
            "plan_summary": data.get("plan_summary"),
            "tests": data.get("tests"),
        }, None
    return None, "no_fixes_in_proposal"


def _decision_from_proposal(proposal_text, config):
    """Build decision with per-fix approval. Uses parsed fixes; each fix checked by risk/confidence."""
    if not proposal_text or not str(proposal_text).strip():
        return {"approved": False, "reason": "no_proposal", "approved_fixes": [], "rejected_fixes": []}
    parsed, err = _parse_proposal_to_fixes(proposal_text)
    if err and not parsed:
        obj = _extract_json(proposal_text)
        if isinstance(obj, dict) and (obj.get("fixes") or obj.get("selected_template_id")):
            parsed, err = _parse_proposal_to_fixes(json.dumps(obj))
        if err or not parsed:
            return {"approved": False, "reason": err or "invalid_proposal", "approved_fixes": [], "rejected_fixes": []}
    approved_fixes = []
    rejected_fixes = []
    for fix in parsed["fixes"]:
        risk = fix.get("risk") or "low"
        confidence = fix.get("confidence") or "low"
        ok = _rank(confidence) >= _rank(config.decision_min_confidence) and _rank(risk) <= _rank(config.decision_max_risk)
        if ok:
            approved_fixes.append(fix)
        else:
            rejected_fixes.append({**fix, "reason": "below_thresholds"})
    return {
        "approved": len(approved_fixes) > 0,
        "reason": "meets_thresholds" if approved_fixes else "below_thresholds",
        "approved_fixes": approved_fixes,
        "rejected_fixes": rejected_fixes,
        "plan_summary": parsed.get("plan_summary"),
        "tests": parsed.get("tests"),
    }


def ingest_node(state):
    args = state["args"]
    docs = fetch_logs_from_trino(Config)
    clusters = build_clusters(docs)
    report = summarize(docs, clusters)
    report_path = write_report(args["output_dir"], report)
    print(f"Fetched {len(docs)} events from Trino")
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
    if state.get("proposal_error"):
        decision = {"approved": False, "reason": state["proposal_error"], "approved_fixes": [], "rejected_fixes": []}
    else:
        decision = _decision_from_proposal(state.get("proposal_text") or "", Config)
    decision["generated_at"] = _now_iso()
    return {"decision": decision}


def apply_node(state):
    decision = state.get("decision", {})
    if not decision.get("approved"):
        print("Apply skipped: decision not approved")
        return {"apply_result": {"applied": False, "reason": "not_approved", "applied_to_repo": False, "per_fix_results": []}}

    approved_fixes = decision.get("approved_fixes") or []
    if not approved_fixes:
        print("Apply skipped: no approved fixes")
        return {"apply_result": {"applied": False, "reason": "no_approved_fixes", "applied_to_repo": False, "per_fix_results": []}}

    repo_path = Config.target_repo_path
    sandbox_dir = Config.sandbox_dir
    per_fix_results = []
    any_applied = False
    any_applied_to_repo = False

    for fix in approved_fixes:
        # Generic LLM patch: patch_content (unified diff) or edits (structured search/replace)
        has_generic = fix.get("patch_content") or (isinstance(fix.get("edits"), list) and len(fix.get("edits", [])) > 0)
        if has_generic:
            result, error = apply_llm_patch(
                repo_path, fix, sandbox_dir, apply_to_repo=Config.apply_to_repo,
                source_prefix=getattr(Config, "target_source_prefix", "") or "",
            )
            if error:
                print(f"Apply skip fix {fix.get('index', '?')} (LLM patch): {error}")
                per_fix_results.append({"fix": fix, "applied": False, "reason": error})
                continue
            any_applied = True
            if result.get("applied_in_repo"):
                any_applied_to_repo = True
            per_fix_results.append({"fix": fix, "applied": True, "sandbox_path": result.get("sandbox_path"), "diff_path": result.get("diff_path")})
            print(f"LLM patch applied; sandbox/diff at {result.get('sandbox_path')}")
            continue

        # Template-based applier (fix has no patch_content or edits)
        template_id = fix.get("selected_template_id")
        if not template_id or not str(template_id).strip():
            print(f"Apply skip fix {fix.get('index', '?')}: fix has no selected_template_id and no patch_content or edits (add patch_content or edits in the proposal to apply)")
            per_fix_results.append({"fix": fix, "applied": False, "reason": "no_template_or_patch"})
            continue
        target_files = fix.get("target_files") or []
        source_paths = resolve_target_paths(repo_path, target_files, getattr(Config, "target_source_prefix", "") or "")
        if not source_paths and len(approved_fixes) == 1:
            fallback = os.path.join(
                repo_path, "src", "main", "java", "com", "example", "authservice", "UserService.java"
            )
            if os.path.isfile(fallback):
                source_paths = [fallback]
        if not source_paths:
            print(f"Apply skip fix {fix.get('index', '?')}: no target files resolved for {target_files}")
            per_fix_results.append({"fix": fix, "applied": False, "reason": "no_target_files"})
            continue
        applier = get_applier(template_id) if template_id else None
        if not applier:
            print(f"Apply skip fix {fix.get('index', '?')}: no applier for template '{template_id}' (available: {list_templates()})")
            per_fix_results.append({"fix": fix, "applied": False, "reason": "unsupported_template"})
            continue
        result, error = applier(source_paths=source_paths, sandbox_dir=sandbox_dir)
        if error:
            print(f"Apply skip fix {fix.get('index', '?')}: {error}")
            per_fix_results.append({"fix": fix, "applied": False, "reason": error})
            continue
        any_applied = True
        per_fix_results.append({"fix": fix, "applied": True, "sandbox_path": result.get("sandbox_path"), "diff_path": result.get("diff_path")})
        print(f"Sandbox patch written to {result['sandbox_path']}")
        if Config.apply_to_repo and result.get("sandbox_path"):
            source_path = source_paths[0]
            with open(result["sandbox_path"], "r", encoding="utf-8") as handle:
                updated = handle.read()
            with open(source_path, "w", encoding="utf-8") as handle:
                handle.write(updated)
            print(f"Applied patch to repo file: {source_path}")
            any_applied_to_repo = True

    return {
        "apply_result": {
            "applied": any_applied,
            "applied_to_repo": any_applied_to_repo,
            "per_fix_results": per_fix_results,
        }
    }


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
    parser = argparse.ArgumentParser(description="LangGraph agent loop (Trino/SWH)")
    parser.add_argument("--output-dir", default=Config.output_dir)
    args = parser.parse_args()

    app = build_graph()
    app.invoke({"args": {"output_dir": args.output_dir}})


if __name__ == "__main__":
    main()
