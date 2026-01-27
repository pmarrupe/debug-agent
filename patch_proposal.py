import json
import os
from datetime import datetime, timezone

from openai import OpenAI


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
                "You are a debugging agent that proposes minimal code fixes. "
                "Return JSON only. Use only the provided templates. "
                "Do not include code diffs, only a patch plan."
            ),
        },
        {
            "role": "user",
            "content": (
                "Given this incident report and allowed templates, propose a "
                "patch plan. Output JSON with fields: plan_summary, "
                "selected_template_id, target_files, rationale, "
                "risk (low|medium|high), confidence (low|medium|high), "
                "tests. Keep target_files as a list of file paths.\n\n"
                f"Incident report:\n{json.dumps(report, indent=2)}\n\n"
                f"Templates:\n{json.dumps(templates, indent=2)}"
            ),
        },
    ]


def propose_patch(report, config):
    if not config.llm_enabled:
        return None, "LLM disabled"
    if config.llm_provider != "openai":
        return None, f"Unsupported LLM provider: {config.llm_provider}"
    if not config.openai_api_key:
        return None, "Missing OPENAI_API_KEY"

    templates = _load_templates(config.template_path)
    client = OpenAI(api_key=config.openai_api_key)
    response = client.chat.completions.create(
        model=config.llm_model,
        messages=_build_prompt(report, templates),
        temperature=0,
    )
    content = response.choices[0].message.content if response.choices else ""
    return content, None


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
