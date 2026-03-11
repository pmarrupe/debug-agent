import json
import os
import subprocess
from datetime import datetime, timezone


def _run(cmd, cwd):
    result = subprocess.run(
        cmd,
        cwd=cwd,
        shell=True,
        capture_output=True,
        text=True,
    )
    return result.returncode, result.stdout.strip(), result.stderr.strip()


def _now_suffix():
    return datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")


def _changed_files(cwd):
    code, out, err = _run("git status --porcelain", cwd)
    if code != 0:
        return None, err or out
    files = []
    for line in out.splitlines():
        path = line[3:]
        if path:
            files.append(path)
    return files, None


def _stage_allowed(cwd, allowed_paths):
    if not allowed_paths:
        return False, "no_allowed_files"
    quoted = " ".join([f"\"{p}\"" for p in allowed_paths])
    code, out, err = _run(f"git add {quoted}", cwd)
    if code != 0:
        return False, err or out
    return True, None


def _create_branch(cwd, branch_name):
    code, out, err = _run(f"git checkout -b {branch_name}", cwd)
    if code != 0:
        return False, err or out
    return True, None


def _commit(cwd, message):
    cmd = (
        "git commit -m \"$(cat <<'EOF'\n"
        f"{message}\n"
        "EOF\n"
        ")\""
    )
    code, out, err = _run(cmd, cwd)
    if code != 0:
        return False, err or out
    return True, None


def _push(cwd, remote):
    code, out, err = _run(f"git push -u {remote} HEAD", cwd)
    if code != 0:
        return False, err or out
    return True, None


def _create_pr(cwd, title, body):
    cmd = (
        "gh pr create "
        f"--title \"{title}\" "
        f"--body \"{body}\""
    )
    code, out, err = _run(cmd, cwd)
    if code != 0:
        return False, err or out
    return True, out


def create_pr_flow(config, decision, apply_result, test_result):
    if not config.pr_enabled:
        return {"created": False, "reason": "pr_disabled"}

    if not apply_result.get("applied_to_repo"):
        return {"created": False, "reason": "not_applied_to_repo"}

    if test_result.get("exit_code") not in (0, None):
        return {"created": False, "reason": "tests_failed"}

    # Collect target_files for PR description
    target_files = []
    for fix in (decision.get("approved_fixes") or []):
        target_files.extend(fix.get("target_files") or [])
    if not target_files:
        target_files = decision.get("target_files") or []

    changed, err = _changed_files(config.target_repo_path)
    if err:
        return {"created": False, "reason": err}
    if not changed:
        return {"created": False, "reason": "no_changes"}

    branch_name = f"{config.pr_branch_prefix}-{_now_suffix()}"
    ok, err = _create_branch(config.target_repo_path, branch_name)
    if not ok:
        return {"created": False, "reason": err}

    # Stage the files that were actually changed by the apply step
    ok, err = _stage_allowed(config.target_repo_path, changed)
    if not ok:
        return {"created": False, "reason": err}

    approved = decision.get("approved_fixes") or []
    template_ids = [f.get("selected_template_id") for f in approved if f.get("selected_template_id")]
    commit_msg = f"{config.pr_title_prefix}: apply {len(approved)} fix(es)"
    if template_ids:
        commit_msg += f" ({', '.join(template_ids)})"
    ok, err = _commit(config.target_repo_path, commit_msg)
    if not ok:
        return {"created": False, "reason": err}

    ok, err = _push(config.target_repo_path, config.pr_remote)
    if not ok:
        return {"created": False, "reason": err}

    body_lines = ["## Summary", f"- Fixes: {len(approved)}", f"- Templates: {', '.join(template_ids or ['patch'])}", f"- Targets: {', '.join(target_files)}", "", "## Test plan", f"- {config.test_command}"]
    body = "\n".join(body_lines)
    ok, out = _create_pr(config.target_repo_path, commit_msg, body)
    if not ok:
        return {"created": False, "reason": out}
    return {"created": True, "url": out}
