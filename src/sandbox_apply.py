import difflib
import os
from datetime import datetime, timezone


def _now_suffix():
    return datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")


def _insert_guard(text, method_signature, guard_block):
    if guard_block in text:
        return text, False
    marker = method_signature
    idx = text.find(marker)
    if idx == -1:
        return text, False
    insert_at = idx + len(marker)
    new_text = text[:insert_at] + "\n" + guard_block + text[insert_at:]
    return new_text, True


def apply_null_check_guard(source_path, sandbox_dir):
    with open(source_path, "r", encoding="utf-8") as handle:
        original = handle.read()

    guard_block = (
        "        if (username == null || username.isBlank()) {\n"
        "            throw new IllegalArgumentException(\"username is required\");\n"
        "        }\n"
        "        if (password == null || password.isBlank()) {\n"
        "            throw new IllegalArgumentException(\"password is required\");\n"
        "        }\n"
    )

    updated = original
    changed_register = False
    changed_login = False

    updated, changed_register = _insert_guard(
        updated,
        "    public User register(String username, String password) {",
        guard_block,
    )
    updated, changed_login = _insert_guard(
        updated,
        "    public boolean login(String username, String password) {",
        guard_block,
    )

    if not (changed_register or changed_login):
        return None, "no_changes_applied"

    os.makedirs(sandbox_dir, exist_ok=True)
    sandbox_path = os.path.join(sandbox_dir, "UserService.java")
    with open(sandbox_path, "w", encoding="utf-8") as handle:
        handle.write(updated)

    diff_path = os.path.join(sandbox_dir, f"patch-{_now_suffix()}.diff")
    diff_lines = difflib.unified_diff(
        original.splitlines(keepends=True),
        updated.splitlines(keepends=True),
        fromfile=source_path,
        tofile=sandbox_path,
    )
    with open(diff_path, "w", encoding="utf-8") as handle:
        handle.writelines(diff_lines)

    return {"sandbox_path": sandbox_path, "diff_path": diff_path}, None
