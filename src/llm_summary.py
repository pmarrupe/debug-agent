import json
import os
from datetime import datetime, timezone

from openai import OpenAI


def _now_suffix():
    return datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")


def _build_prompt(report):
    return [
        {
            "role": "system",
            "content": (
                "You are a debugging assistant. Return a JSON object only. "
                "Summarize clusters, propose likely root cause, suggested fix, "
                "risk level (low|medium|high), confidence (low|medium|high), "
                "and a minimal test plan."
            ),
        },
        {
            "role": "user",
            "content": (
                "Here is the incident report JSON. Produce a JSON summary with "
                "a 'summary' string and a 'clusters' array. Each cluster should "
                "include: key, error_type, diagnosis, suggested_fix, risk, "
                "confidence, tests.\n\n"
                f"{json.dumps(report, indent=2)}"
            ),
        },
    ]


def summarize_report(report, config):
    if not config.llm_enabled:
        return None, "LLM disabled"
    if config.llm_provider != "openai":
        return None, f"Unsupported LLM provider: {config.llm_provider}"
    if not config.openai_api_key:
        return None, "Missing OPENAI_API_KEY"

    client = OpenAI(api_key=config.openai_api_key)
    response = client.chat.completions.create(
        model=config.llm_model,
        messages=_build_prompt(report),
        temperature=0,
    )
    content = response.choices[0].message.content if response.choices else ""
    return content, None


def write_summary(output_dir, report, summary_text, error_message=None):
    os.makedirs(output_dir, exist_ok=True)
    filename = f"summary-{_now_suffix()}.json"
    path = os.path.join(output_dir, filename)
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "error": error_message,
        "summary": None,
    }
    if summary_text:
        try:
            payload["summary"] = json.loads(summary_text)
        except json.JSONDecodeError:
            payload["summary"] = {"raw": summary_text}
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2)
    return path

