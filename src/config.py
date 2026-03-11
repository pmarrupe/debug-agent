import os


def get_env(name, default):
    value = os.getenv(name)
    return value if value is not None and value != "" else default


class Config:
    base_dir = os.path.dirname(__file__)
    project_root = os.path.abspath(os.path.join(base_dir, ".."))
    output_dir = get_env("AGENT_OUTPUT_DIR", "output")
    # Trino / SWH log source
    trino_host = get_env("TRINO_HOST", "sql.wdpharos.io")
    trino_port = int(get_env("TRINO_PORT", "443"))
    trino_catalog = get_env("TRINO_CATALOG", "dw")
    trino_client_id = get_env("TRINO_CLIENT_ID", "")
    trino_client_secret = get_env("TRINO_CLIENT_SECRET", "")
    trino_token_url = get_env(
        "TRINO_TOKEN_URL",
        "https://prod-us.auth.wdpharos.io/token?scope=openid%20createnew",
    )
    trino_sql = get_env("TRINO_SQL", "")
    trino_sql_file = get_env("TRINO_SQL_FILE", "")
    trino_verify_ssl = get_env("TRINO_VERIFY_SSL", "false").lower() in ("1", "true", "yes")
    llm_enabled = get_env("LLM_ENABLED", "false").lower() in ("1", "true", "yes")
    llm_provider = get_env("LLM_PROVIDER", "openai")  # "openai" | "internal" (OpenAI-compatible CIS)
    llm_model = get_env("LLM_MODEL", "gpt-4o-mini")
    openai_api_key = get_env("OPENAI_API_KEY", "")
    # Internal / Centralized Inference Service (OpenAI-compatible API)
    llm_base_url = get_env("LLM_BASE_URL", "")  # e.g. https://s0010-ml-https..../ml/inference/cis/v1alpha1
    llm_api_key = get_env("LLM_API_KEY", "")   # Value for auth header (e.g. username or key)
    llm_auth_header = get_env("LLM_AUTH_HEADER", "Wd-PCA-Feature-Key")  # CIS feature key header
    llm_verify_ssl = get_env("LLM_VERIFY_SSL", "true").lower() in ("1", "true", "yes")
    llm_extra_query = get_env("LLM_EXTRA_QUERY", "")  # e.g. bypass_auth=true (appended to requests)
    # CIS uses a different path than /chat/completions; set e.g. openai-chat-completion-v1
    llm_chat_path = get_env("LLM_CHAT_PATH", "")  # if set, POST to base_url/llm_chat_path (no /chat/completions)
    llm_timeout = float(get_env("LLM_TIMEOUT", "300"))  # seconds for LLM read timeout (patch proposal on large reports can take 2–5 min)
    llm_output_dir = get_env("LLM_OUTPUT_DIR", output_dir)
    proposal_output_dir = get_env("PROPOSAL_OUTPUT_DIR", output_dir)
    template_path = get_env("TEMPLATE_PATH", "templates.json")
    decision_min_confidence = get_env("DECISION_MIN_CONFIDENCE", "medium")
    decision_max_risk = get_env("DECISION_MAX_RISK", "medium")
    target_repo_path = get_env("TARGET_REPO_PATH", os.path.join(project_root, "..", "ui-server-2"))
    # If repo is multi-module (e.g. ui-server-2 with ui/src/main/java/...), set e.g. "ui" so paths like src/main/java/... resolve to <repo>/ui/src/main/java/...
    target_source_prefix = get_env("TARGET_SOURCE_PREFIX", "").strip()
    sandbox_dir = get_env("SANDBOX_DIR", os.path.join(project_root, "sandbox"))
    apply_to_repo = get_env("APPLY_TO_REPO", "false").lower() in ("1", "true", "yes")
    test_command = get_env("TEST_COMMAND", "mvn test")
    pr_enabled = get_env("PR_ENABLED", "false").lower() in ("1", "true", "yes")
    pr_base_branch = get_env("PR_BASE_BRANCH", "main")
    pr_branch_prefix = get_env("PR_BRANCH_PREFIX", "agent-fix")
    pr_remote = get_env("PR_REMOTE", "origin")
    pr_title_prefix = get_env("PR_TITLE_PREFIX", "agent")

