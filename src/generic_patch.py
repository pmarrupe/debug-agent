"""
Apply LLM-generated patches: unified diff (patch_content) or structured edits (edits).
Enables the agent to apply arbitrary fixes suggested by the LLM, not just template-based appliers.
"""

import os
import subprocess
import tempfile
from datetime import datetime, timezone
from typing import List, Optional

def _now_suffix():
    return datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")


def _apply_unified_diff(
    repo_path: str,
    patch_content: str,
    sandbox_dir: str,
    apply_to_repo: bool,
    source_prefix: str = "",
) -> tuple[Optional[dict], Optional[str]]:
    """
    Apply a unified diff using the `patch` command.
    Saves the diff to sandbox_dir for audit; optionally applies in repo.
    If source_prefix is set (e.g. "ui"), patch is run from repo_path/source_prefix so paths like src/main/java/... resolve correctly.
    """
    patch_content = (patch_content or "").strip()
    if not patch_content:
        return None, "empty_patch_content"
    # Ensure patch has a newline at end (patch command can be strict)
    if not patch_content.endswith("\n"):
        patch_content += "\n"
    os.makedirs(sandbox_dir, exist_ok=True)
    diff_path = os.path.join(sandbox_dir, f"llm-patch-{_now_suffix()}.diff")
    with open(diff_path, "w", encoding="utf-8") as f:
        f.write(patch_content)
    if not apply_to_repo:
        return {"sandbox_path": diff_path, "diff_path": diff_path, "applied_in_repo": False}, None
    cwd = os.path.normpath(os.path.join(repo_path, source_prefix)) if source_prefix else repo_path
    if not os.path.isdir(cwd):
        return None, f"patch cwd not found: {cwd}"
    # Run patch in repo (or repo/source_prefix); -p1 strips one path component (e.g. a/ or b/) from diff paths.
    # stdin=DEVNULL prevents patch from blocking on interactive prompts (e.g. "File to patch?").
    result = subprocess.run(
        ["patch", "-p1", "--forward", "--input", diff_path],
        cwd=cwd,
        capture_output=True,
        text=True,
        stdin=subprocess.DEVNULL,
    )
    if result.returncode != 0:
        err = (result.stderr or result.stdout or "unknown").strip()
        try:
            with open(diff_path, "r", encoding="utf-8") as f:
                lines = f.readlines()
            line14 = lines[13].rstrip() if len(lines) >= 14 else ""
            if line14:
                err = f"{err} (patch line 14: {line14!r})"
        except Exception:
            pass
        return None, f"patch failed: {err}. Saved patch: {diff_path}"
    return {"sandbox_path": diff_path, "diff_path": diff_path, "applied_in_repo": True}, None


def _apply_structured_edits(
    repo_path: str,
    edits: List[dict],
    sandbox_dir: str,
    apply_to_repo: bool,
    source_prefix: str = "",
) -> tuple[Optional[dict], Optional[str]]:
    """
    Apply a list of edits: each { "file": "path/to/file.java", "old_string": "...", "new_string": "..." }.
    Path is relative to repo_path (or repo_path/source_prefix if set). Uses same path resolution as template appliers.
    """
    if not edits or not isinstance(edits, list):
        return None, "no_edits"
    try:
        from template_appliers import resolve_target_paths
    except ImportError:
        resolve_target_paths = None
    repo_abs = os.path.abspath(repo_path)
    modified_paths = []
    os.makedirs(sandbox_dir, exist_ok=True)
    for i, edit in enumerate(edits):
        if not isinstance(edit, dict):
            continue
        file_rel = (edit.get("file") or edit.get("path") or "").strip().lstrip("/")
        old_str = edit.get("old_string")
        new_str = edit.get("new_string")
        if not file_rel or old_str is None:
            return None, f"edit[{i}]: missing file or old_string"
        if new_str is None:
            new_str = ""
        if resolve_target_paths:
            resolved = resolve_target_paths(repo_path, [file_rel], source_prefix)
            source_path = resolved[0] if resolved else None
        else:
            prefix_abs = os.path.normpath(os.path.join(repo_abs, source_prefix)) if source_prefix else repo_abs
            candidate = os.path.normpath(os.path.join(prefix_abs, file_rel))
            source_path = candidate if os.path.isfile(candidate) and candidate.startswith(repo_abs) else None
            if not source_path:
                candidate = os.path.normpath(os.path.join(repo_abs, file_rel))
                source_path = candidate if os.path.isfile(candidate) and candidate.startswith(repo_abs) else None
        if not source_path:
            return None, f"edit[{i}]: file not found or outside repo: {file_rel}"
        try:
            with open(source_path, "r", encoding="utf-8") as f:
                content = f.read()
        except Exception as e:
            return None, f"edit[{i}]: read failed: {e}"
        if old_str not in content:
            return None, f"edit[{i}]: old_string not found in file (exact match required)"
        new_content = content.replace(old_str, new_str, 1)
        # Write to sandbox (same relative path under sandbox_dir)
        sandbox_file = os.path.join(sandbox_dir, file_rel)
        d = os.path.dirname(sandbox_file)
        if d:
            os.makedirs(d, exist_ok=True)
        with open(sandbox_file, "w", encoding="utf-8") as f:
            f.write(new_content)
        modified_paths.append(sandbox_file)
        if apply_to_repo:
            with open(source_path, "w", encoding="utf-8") as f:
                f.write(new_content)
    return {
        "sandbox_path": modified_paths[0] if modified_paths else None,
        "diff_path": os.path.join(sandbox_dir, f"llm-edits-{_now_suffix()}.json"),
        "modified_paths": modified_paths,
        "applied_in_repo": apply_to_repo,
    }, None


def apply_llm_patch(
    repo_path: str,
    fix: dict,
    sandbox_dir: str,
    apply_to_repo: bool = False,
    source_prefix: str = "",
) -> tuple[Optional[dict], Optional[str]]:
    """
    Apply an LLM-generated fix. The fix may contain:
    - patch_content: unified diff string (applied with `patch -p1`).
    - edits: list of { file, old_string, new_string } (search/replace in repo files).
    If source_prefix is set (e.g. "ui"), paths are resolved under repo_path/source_prefix for multi-module layouts.
    """
    patch_content = fix.get("patch_content")
    if isinstance(patch_content, str) and patch_content.strip():
        return _apply_unified_diff(repo_path, patch_content, sandbox_dir, apply_to_repo, source_prefix)
    edits = fix.get("edits")
    if isinstance(edits, list) and len(edits) > 0:
        return _apply_structured_edits(repo_path, edits, sandbox_dir, apply_to_repo, source_prefix)
    return None, "no patch_content or edits in fix"
