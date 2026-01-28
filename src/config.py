import os


def get_env(name, default):
    value = os.getenv(name)
    return value if value is not None and value != "" else default


class Config:
    base_dir = os.path.dirname(__file__)
    project_root = os.path.abspath(os.path.join(base_dir, ".."))
    es_hosts = get_env("ES_HOSTS", "http://localhost:9200").split(",")
    index_pattern = get_env("ES_INDEX_PATTERN", "logs-auth-service-*")
    lookback_minutes = int(get_env("LOOKBACK_MINUTES", "60"))
    query_size = int(get_env("ES_QUERY_SIZE", "1000"))
    output_dir = get_env("AGENT_OUTPUT_DIR", "output")
    llm_enabled = get_env("LLM_ENABLED", "false").lower() in ("1", "true", "yes")
    llm_provider = get_env("LLM_PROVIDER", "openai")
    llm_model = get_env("LLM_MODEL", "gpt-4o-mini")
    openai_api_key = get_env("OPENAI_API_KEY", "")
    llm_output_dir = get_env("LLM_OUTPUT_DIR", output_dir)
    proposal_output_dir = get_env("PROPOSAL_OUTPUT_DIR", output_dir)
    template_path = get_env("TEMPLATE_PATH", "templates.json")
    decision_min_confidence = get_env("DECISION_MIN_CONFIDENCE", "medium")
    decision_max_risk = get_env("DECISION_MAX_RISK", "medium")
    target_repo_path = get_env("TARGET_REPO_PATH", os.path.join(project_root, "..", "auth-service"))
    sandbox_dir = get_env("SANDBOX_DIR", os.path.join(project_root, "sandbox"))
    apply_to_repo = get_env("APPLY_TO_REPO", "false").lower() in ("1", "true", "yes")
    test_command = get_env("TEST_COMMAND", "mvn test")
    pr_enabled = get_env("PR_ENABLED", "false").lower() in ("1", "true", "yes")
    pr_base_branch = get_env("PR_BASE_BRANCH", "main")
    pr_branch_prefix = get_env("PR_BRANCH_PREFIX", "agent-fix")
    pr_remote = get_env("PR_REMOTE", "origin")
    pr_title_prefix = get_env("PR_TITLE_PREFIX", "agent")

