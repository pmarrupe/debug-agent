import json
import os
from datetime import datetime, timezone

from llm_client import get_llm_client


def _now_suffix():
    return datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")


def _load_templates(path):
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def _build_prompt(report, templates):
    return [
        {
            "role": "system",
            "content": (
                "You are a debugging agent that proposes minimal code fixes. Return JSON only. "
                "For the agent to APPLY a fix, each fix object MUST include one of: (1) selected_template_id + target_files, "
                "or (2) patch_content (unified diff string), or (3) edits (array of file + old_string + new_string). "
                "Without one of these, the agent will skip the fix. Always provide patch_content or edits when you can so the agent can apply your fix."
            ),
        },
        {
            "role": "user",
            "content": (
                "Given this incident report, propose fixes. Output JSON with plan_summary and a 'fixes' array.\n\n"
                "REQUIRED for each fix (the agent needs one of these to apply):\n"
                "- selected_template_id (from the templates list) AND target_files (array of paths), OR\n"
                "- patch_content (string): valid unified diff. Format: '--- a/src/main/java/.../File.java\\n+++ b/src/main/java/.../File.java\\n@@ -N,M +N,M @@\\n' then lines starting with space (context), - (remove), + (add). No trailing spaces on context lines; use \\n for newlines. Agent runs 'patch -p1'.\n"
                "- edits (array): [ { \"file\": \"src/main/java/.../File.java\", \"old_string\": \"exact line(s) to find\", \"new_string\": \"replacement\" } ]. Path relative to repo. old_string must appear exactly once in the file.\n\n"
                "Also include per fix: rationale (optional), risk (low|medium|high), confidence (low|medium|high), and optionally error_type or cluster_key.\n\n"
                "You MUST provide patch_content or edits for every fix you want the agent to apply. Prefer 'edits' over patch_content when possible (edits are search/replace and less error-prone than unified diff). Template-only fixes work only for null-check-guard; for other fixes use patch_content or edits.\n\n"
                f"Incident report:\n{json.dumps(report, indent=2)}\n\n"
                f"Templates:\n{json.dumps(templates, indent=2)}"
            ),
        },
    ]


def propose_patch(report, config):
    if not config.llm_enabled:
        return None, "LLM disabled"
    try:
        client = get_llm_client(config)
    except ValueError as e:
        return None, str(e)

    templates = _load_templates(config.template_path)
    try:
        response = client.chat.completions.create(
            model=config.llm_model,
            messages=_build_prompt(report, templates),
            temperature=0,
        )
        content = response.choices[0].message.content if response.choices else ""
        return content, None
    except Exception as e:
        return None, f"{type(e).__name__}: {e}"


def write_proposal(output_dir, proposal_text, error_message=None):
    os.makedirs(output_dir, exist_ok=True)
    filename = f"proposal-{_now_suffix()}.json"
    path = os.path.join(output_dir, filename)
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "error": error_message,
        "proposal": None,
    }
    if proposal_text:
        try:
            payload["proposal"] = json.loads(proposal_text)
        except json.JSONDecodeError:
            payload["proposal"] = {"raw": proposal_text}
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2)
    return path
