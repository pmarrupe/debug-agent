# Log Debugging Agent (Python)

## What it does
- Pulls recent error logs from SWH via Trino (data warehouse).
- Clusters exceptions by stack signature.
- Writes a JSON report, LLM summary, and patch proposal (and optionally apply + PR via LangGraph).
- **Reads the LLM proposal** and normalizes it to a list of fixes (supports one fix or multiple per exception/cluster).
- **Applies patches per fix**: for each approved fix (by risk/confidence), either (1) runs the template applier for that template id, or (2) **applies an LLM-generated patch** directly: unified diff (`patch_content`) or structured edits (`edits`: file + old_string/new_string). This lets the agent fix any error type the LLM can describe as a concrete patch, not only predefined templates.

## Setup
```bash
cd /path/to/debug-agent
python3 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

---

## Parameters needed to run

### 1. SQL / Trino (log source) — required for any run

| Param | Required | Default | Description |
|-------|----------|---------|-------------|
| `TRINO_CLIENT_ID` | **Yes** | — | OAuth2 client ID for SWH. |
| `TRINO_CLIENT_SECRET` | **Yes** | — | OAuth2 client secret. |
| `TRINO_SQL` or `TRINO_SQL_FILE` | **One required** | — | SQL that returns columns: `message_severity`, `exception_class`, `exception_root_class`, `stack_trace`. |
| `TRINO_HOST` | No | `sql.wdpharos.io` | Trino host. |
| `TRINO_PORT` | No | `443` | Trino port. |
| `TRINO_CATALOG` | No | `dw` | Trino catalog. |
| `TRINO_TOKEN_URL` | No | prod-us auth URL | OAuth2 token URL for JWT. |
| `TRINO_VERIFY_SSL` | No | `false` | Set `true` to verify TLS. |

**Example Trino SQL** (partition filter required; use `wd_event_date` as date or varchar per your schema):
```sql
SELECT message_severity, exception_class, exception_root_class, stack_trace
FROM dw.swh.ui_exception_log
WHERE wd_env_type = 'PROD'
  AND wd_event_date >= CAST(current_date - INTERVAL '1' DAY AS VARCHAR)
  AND wd_event_date < CAST(current_date + INTERVAL '1' DAY AS VARCHAR)
LIMIT 100
```

### 2. LLM — required for summary + proposal

**Option A: Internal CIS (recommended for ui-server)**

| Param | Required | Default | Description |
|-------|----------|---------|-------------|
| `LLM_ENABLED` | **Yes** | `false` | Set `true` to call LLM. |
| `LLM_PROVIDER` | **Yes** | `openai` | Set `internal` for CIS. |
| `LLM_BASE_URL` | **Yes** | — | Must end with `/v1alpha1/openai/v1` (e.g. `https://s0010-ml-https..../ml/inference/cis/v1alpha1/openai/v1`). |
| `LLM_API_KEY` | **Yes** | — | Value for `Wd-PCA-Feature-Key` header (e.g. `$(whoami)` or `bypass-auth`). |
| `LLM_MODEL` | **Yes** | `gpt-4o-mini` | Use `provider/model` (e.g. `aviato-turbo/aviato-turbo`). List: `curl -H "Wd-PCA-Feature-Key: $(whoami)" -k '.../v1alpha1/models?bypass_auth=true'`. |
| `LLM_VERIFY_SSL` | No | `true` | Set `false` on dev if you don’t have the Alpaca cert bundle. |
| `LLM_EXTRA_QUERY` | No | — | e.g. `bypass_auth=true` for CIS. |
| `LLM_AUTH_HEADER` | No | `Wd-PCA-Feature-Key` | Header name for CIS. |
| `LLM_CHAT_PATH` | No | — | Leave unset for standard CIS OpenAI endpoint. |

**Option B: OpenAI**

| Param | Required | Default | Description |
|-------|----------|---------|-------------|
| `LLM_ENABLED` | **Yes** | `false` | Set `true`. |
| `LLM_PROVIDER` | No | `openai` | Keep `openai`. |
| `OPENAI_API_KEY` | **Yes** | — | Your OpenAI API key. |
| `LLM_MODEL` | No | `gpt-4o-mini` | Model name. |

---

## Run

**Minimal (Trino only, no LLM):** report only.
```bash
export TRINO_CLIENT_ID=your_client_id
export TRINO_CLIENT_SECRET=your_client_secret
export TRINO_SQL="SELECT message_severity, exception_class, exception_root_class, stack_trace FROM dw.swh.ui_exception_log WHERE wd_env_type = 'PROD' AND wd_event_date >= CAST(current_date - INTERVAL '1' DAY AS VARCHAR) AND wd_event_date < CAST(current_date + INTERVAL '1' DAY AS VARCHAR) LIMIT 100"

PYTHONPATH=src python src/main.py
```

**Full (Trino + internal CIS LLM):** report + summary + proposal written to `output/`.
```bash
# SQL / Trino (required)
export TRINO_CLIENT_ID=your_client_id
export TRINO_CLIENT_SECRET=your_client_secret
export TRINO_SQL="SELECT message_severity, exception_class, exception_root_class, stack_trace FROM dw.swh.ui_exception_log WHERE wd_env_type = 'PROD' AND wd_event_date >= CAST(current_date - INTERVAL '1' DAY AS VARCHAR) AND wd_event_date < CAST(current_date + INTERVAL '1' DAY AS VARCHAR) LIMIT 100"

# LLM (internal CIS)
export LLM_ENABLED=true
export LLM_PROVIDER=internal
export LLM_BASE_URL=https://s0010-ml-https.s0010.us-west-2.awswd/ml/inference/cis/v1alpha1/openai/v1
export LLM_API_KEY=$(whoami)
export LLM_MODEL=aviato-turbo/aviato-turbo
export LLM_VERIFY_SSL=false
export LLM_EXTRA_QUERY=bypass_auth=true

PYTHONPATH=src python src/main.py
```

**Full with OpenAI instead of CIS:**
```bash
# SQL / Trino (same as above)
export TRINO_CLIENT_ID=...
export TRINO_CLIENT_SECRET=...
export TRINO_SQL="..."

# LLM (OpenAI)
export LLM_ENABLED=true
export OPENAI_API_KEY=your_openai_key
export LLM_MODEL=gpt-4o-mini

PYTHONPATH=src python src/main.py
```

**LangGraph (same params + optional apply/PR):**
```bash
# Set all Trino + LLM vars as above, then:
export APPLY_TO_REPO=false   # set true to write patches to repo
export PR_ENABLED=false      # set true to create PRs after apply + tests

PYTHONPATH=src python src/graph.py
```

---

## All config (env vars)

**Trino / SWH:** `TRINO_HOST`, `TRINO_PORT`, `TRINO_CATALOG`, `TRINO_CLIENT_ID`, `TRINO_CLIENT_SECRET`, `TRINO_TOKEN_URL`, `TRINO_SQL` or `TRINO_SQL_FILE`, `TRINO_VERIFY_SSL`.

**Output:** `AGENT_OUTPUT_DIR` (default: `output`), `LLM_OUTPUT_DIR`, `PROPOSAL_OUTPUT_DIR`.

**LLM:** `LLM_ENABLED`, `LLM_PROVIDER`, `LLM_MODEL`, `OPENAI_API_KEY` (openai), `LLM_BASE_URL`, `LLM_API_KEY`, `LLM_AUTH_HEADER`, `LLM_VERIFY_SSL`, `LLM_EXTRA_QUERY`, `LLM_CHAT_PATH`, `LLM_TIMEOUT` (seconds, default 300; increase if patch proposal still times out).

**Pipeline:** `TEMPLATE_PATH`, `DECISION_MIN_CONFIDENCE`, `DECISION_MAX_RISK`, `TARGET_REPO_PATH`, `TARGET_SOURCE_PREFIX`, `SANDBOX_DIR`, `APPLY_TO_REPO`, `TEST_COMMAND`, `PR_ENABLED`, `PR_BASE_BRANCH`, `PR_BRANCH_PREFIX`, `PR_REMOTE`, `PR_TITLE_PREFIX`.

---

## Targeting ui-server (default)

The agent is configured to target **ui-server** (not the old auth-service). The default repo path is `../ui-server-2` relative to the debug-agent project, so with a layout like:

```
code/
  debug-agent/    # this repo
  ui-server-2/    # repo to analyze and (optionally) patch
```

no extra config is needed.

If your ui-server clone is elsewhere, set the absolute path. **ui-server-2 is multi-module** (sources under `ui/src/main/java/...`, not `src/main/java/...`). Set `TARGET_SOURCE_PREFIX=ui` so the agent resolves paths like `src/main/java/com/workday/...` under `<repo>/ui/`:

```bash
export TARGET_REPO_PATH=/Users/prashanth.vardhan/Documents/code/ui-server-2
export TARGET_SOURCE_PREFIX=ui
```

Then run `main.py` or `graph.py` as usual. Report, summary, and proposal are driven by Trino (ui_exception_log) and apply to the ui-server context. The **apply** step uses the proposal’s fixes: each fix can be template-based (template id + target_files) or an LLM-generated patch (`patch_content` unified diff or `edits` search/replace); the agent applies each approved fix and optionally writes to the repo and creates a PR.

