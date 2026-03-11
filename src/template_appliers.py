"""
Template applier registry and path resolution for applying LLM-suggested fixes.

- Registry maps template_id -> applier(source_paths, sandbox_dir, **kwargs) -> (result_dict, error_str).
- Path resolution turns proposal target_files (names or relative paths) into absolute paths under the repo.
"""

import os
from typing import Callable, List, Optional

# Type: (source_paths: List[str], sandbox_dir: str, **kwargs) -> (Optional[dict], Optional[str])
ApplierFn = Callable[..., tuple[Optional[dict], Optional[str]]]

_REGISTRY: dict[str, ApplierFn] = {}


def register(template_id: str):
    """Decorator to register an applier for a template_id."""

    def _decorator(fn: ApplierFn):
        _REGISTRY[template_id] = fn
        return fn

    return _decorator


def get_applier(template_id: str) -> Optional[ApplierFn]:
    """Return the applier for template_id, or None if not registered."""
    return _REGISTRY.get(template_id)


def list_templates() -> List[str]:
    """Return list of registered template IDs."""
    return list(_REGISTRY.keys())


def resolve_target_paths(repo_path: str, target_files: List[str], source_prefix: str = "") -> List[str]:
    """
    Resolve proposal target_files to absolute paths under repo_path.

    - If an item is a filename (e.g. "UserService.java"), search the repo and return matches.
    - If an item looks like a path (contains / or \\), join with repo_path (and optionally source_prefix, e.g. "ui").
    - If direct join fails, search repo for any file whose path ends with the requested path (for multi-module layouts).
    - Only returns paths that exist and are under repo_path.
    """
    repo_abs = os.path.abspath(repo_path)
    resolved: List[str] = []
    seen: set[str] = set()
    norm_item = lambda s: s.replace("\\", "/").strip().lstrip("/")

    for item in target_files or []:
        item = (item or "").strip()
        if not item:
            continue
        item_norm = norm_item(item)
        if os.path.sep in item or "/" in item:
            # Try direct join, then with source_prefix (e.g. ui/src/main/java/...)
            candidates_to_try = [os.path.normpath(os.path.join(repo_abs, item_norm))]
            if source_prefix:
                candidates_to_try.append(os.path.normpath(os.path.join(repo_abs, source_prefix, item_norm)))
            found = False
            for candidate in candidates_to_try:
                if candidate in seen:
                    found = True
                    break
                if os.path.isfile(candidate) and candidate.startswith(repo_abs):
                    resolved.append(candidate)
                    seen.add(candidate)
                    found = True
                    break
            if found:
                continue
            # Fallback 1: find file by exact path suffix (e.g. ui/src/main/java/.../File.java tail matches src/main/java/.../File.java)
            base_name = os.path.basename(item_norm)
            item_parts = item_norm.split("/")
            for root, _dirs, files in os.walk(repo_abs):
                if base_name not in files:
                    continue
                candidate = os.path.join(root, base_name)
                if candidate in seen:
                    continue
                try:
                    rel = os.path.relpath(candidate, repo_abs).replace("\\", "/")
                except ValueError:
                    continue
                rel_parts = rel.split("/")
                if rel_parts[-len(item_parts):] == item_parts and os.path.isfile(candidate) and candidate.startswith(repo_abs):
                    resolved.append(candidate)
                    seen.add(candidate)
                    break
                if len(resolved) >= 20:
                    break
            else:
                # Fallback 2: same basename under src/main/java (LLM path may be wrong, e.g. ui/config vs ui/web/config)
                if base_name.endswith(".java") and "src/main/java" in item_norm:
                    candidates_fallback = []
                    for root, _dirs, files in os.walk(repo_abs):
                        if base_name not in files:
                            continue
                        candidate = os.path.join(root, base_name)
                        if candidate in seen:
                            continue
                        try:
                            rel = os.path.relpath(candidate, repo_abs).replace("\\", "/")
                        except ValueError:
                            continue
                        if "src/main/java" in rel and candidate.startswith(repo_abs) and os.path.isfile(candidate):
                            candidates_fallback.append((candidate, rel))
                        if len(candidates_fallback) >= 20:
                            break
                    if candidates_fallback:
                        # Prefer path under source_prefix if set (e.g. ui/src/main/java/...)
                        if source_prefix:
                            under_prefix = [c for c in candidates_fallback if c[1].startswith(source_prefix + "/")]
                            if under_prefix:
                                candidates_fallback = under_prefix
                        c, _ = candidates_fallback[0]
                        resolved.append(c)
                        seen.add(c)
            continue
        # Treat as filename: walk repo to find it
        for root, _dirs, files in os.walk(repo_abs):
            if item in files:
                candidate = os.path.join(root, item)
                if candidate not in seen:
                    resolved.append(candidate)
                    seen.add(candidate)
            if len(resolved) >= 20:
                break

    return resolved


def _adapt_single_file(
    fn: Callable[[str, str], tuple[Optional[dict], Optional[str]]]
) -> ApplierFn:
    """Adapt (source_path, sandbox_dir) -> (result, error) to (source_paths, sandbox_dir) -> (result, error)."""

    def adapted(source_paths: List[str], sandbox_dir: str, **kwargs):
        if not source_paths:
            return None, "no_target_files"
        return fn(source_paths[0], sandbox_dir)

    return adapted


def _register_builtin_appliers():
    from sandbox_apply import (
        apply_null_check_guard,
        apply_input_validation_guard,
        apply_retry_backoff,
        apply_timeout_tuning,
        apply_feature_flag,
    )

    _REGISTRY["null-check-guard"] = _adapt_single_file(apply_null_check_guard)
    _REGISTRY["input-validation"] = _adapt_single_file(apply_input_validation_guard)
    _REGISTRY["retry-backoff"] = _adapt_single_file(apply_retry_backoff)
    _REGISTRY["timeout-tuning"] = _adapt_single_file(apply_timeout_tuning)
    _REGISTRY["feature-flag"] = _adapt_single_file(apply_feature_flag)


_register_builtin_appliers()
