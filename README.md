# Log Debugging Agent (Python)

## What it does
- Pulls recent error logs from Elasticsearch.
- Clusters exceptions by stack signature.
- Writes a JSON report with top clusters.

## Setup
```bash
cd /Users/prashanth_1/Downloads/code/debug-agent
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Run
```bash
APPLY_TO_REPO=true \
LLM_ENABLED=true \
PR_ENABLED=true \
OPENAI_API_KEY=your_key \
PYTHONPATH=src python src/graph.py
```

## Config (env vars)
- `ES_HOSTS` (default: `http://localhost:9200`)
- `ES_INDEX_PATTERN` (default: `logs-auth-service-*`)
- `LOOKBACK_MINUTES` (default: `60`)
- `ES_QUERY_SIZE` (default: `1000`)
- `AGENT_OUTPUT_DIR` (default: `output`)
- `LLM_ENABLED` (default: `false`)
- `LLM_PROVIDER` (default: `openai`)
- `LLM_MODEL` (default: `gpt-4o-mini`)
- `OPENAI_API_KEY` (required when `LLM_ENABLED=true`)
- `LLM_OUTPUT_DIR` (default: `output`)
- `PROPOSAL_OUTPUT_DIR` (default: `output`)
- `TEMPLATE_PATH` (default: `templates.json`)
- `DECISION_MIN_CONFIDENCE` (default: `medium`)
- `DECISION_MAX_RISK` (default: `medium`)
- `TARGET_REPO_PATH` (default: `../auth-service`)
- `SANDBOX_DIR` (default: `sandbox`)
- `APPLY_TO_REPO` (default: `false`)
- `TEST_COMMAND` (default: `mvn test`)
- `PR_ENABLED` (default: `false`)
- `PR_BASE_BRANCH` (default: `main`)
- `PR_BRANCH_PREFIX` (default: `agent-fix`)
- `PR_REMOTE` (default: `origin`)
- `PR_TITLE_PREFIX` (default: `agent`)

