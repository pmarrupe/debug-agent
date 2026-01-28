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
PYTHONPATH=src python src/main.py
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

## Example
```bash
ES_HOSTS=http://localhost:9200 \
ES_INDEX_PATTERN=logs-auth-service-* \
LOOKBACK_MINUTES=60 \
PYTHONPATH=src python src/main.py
```

## LLM Summary (suggest-only)
```bash
LLM_ENABLED=true \
OPENAI_API_KEY=your_key \
PYTHONPATH=src python src/main.py
```

## Patch Proposal (suggest-only)
Uses allowlisted templates from `templates.json`.

## LangGraph Agent Loop (suggest-only)
```bash
LLM_ENABLED=true \
OPENAI_API_KEY=your_key \
PYTHONPATH=src python src/graph.py
```

Note: Only `report-*.json` and `decision-*.json` are written. Summary and proposal
are generated in memory only.

## Sandbox Patch Output
When a decision is approved and the template is supported, a sandbox copy and diff
are written to the `sandbox/` directory. The main codebase is not modified.

## Test Gate
If `APPLY_TO_REPO=true`, the patch is applied to the repo and tests run using
`TEST_COMMAND`. The decision output includes the test result.

## PR Creation
If `PR_ENABLED=true`, the agent will create a branch, commit allowed files, push,
and open a PR using `gh`. Requires GitHub CLI auth.

