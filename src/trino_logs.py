"""
Fetch log rows from SWH via Trino and map to the doc shape expected by the pipeline.
Uses client_credentials to get JWT, then executes SQL (TRINO_SQL or TRINO_SQL_FILE).
Maps: message_severity → log.level, exception_class → error.type + message,
      stack_trace → error.stack_trace; @timestamp left empty (not in query).
"""

import os
from typing import List
import urllib3

import requests
import trino
from trino.auth import JWTAuthentication

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


def get_trino_jwt(client_id: str, client_secret: str, token_url: str) -> str:
    """Get JWT via OAuth2 client_credentials. Returns id_token."""
    response = requests.post(
        token_url,
        files={
            "grant_type": (None, "client_credentials"),
            "client_id": (None, client_id),
            "client_secret": (None, client_secret),
        },
        verify=False,
    )
    if response.status_code != 200:
        raise RuntimeError(
            f"Trino token request failed: {response.status_code} {response.text}"
        )
    return response.json()["id_token"]


def _resolve_sql(config) -> str:
    if config.trino_sql_file and os.path.isfile(config.trino_sql_file):
        with open(config.trino_sql_file, "r", encoding="utf-8") as f:
            return f.read().strip()
    if config.trino_sql:
        return config.trino_sql.strip()
    raise ValueError(
        "Set TRINO_SQL or TRINO_SQL_FILE to provide the query to run."
    )


def _row_to_doc(row: tuple, col_names: list) -> dict:
    """Map a Trino row to a log doc: log.level, error.type, message, error.stack_trace, @timestamp."""
    by_name = dict(zip(col_names, row))
    severity = (by_name.get("message_severity") or "") if col_names else ""
    exc_class = (by_name.get("exception_class") or "") if col_names else ""
    stack = (by_name.get("stack_trace") or "") if col_names else ""
    message = exc_class
    if stack and "\n" in str(stack):
        message = str(stack).split("\n")[0].strip() or exc_class
    return {
        "@timestamp": "",
        "message": message,
        "log.level": severity,
        "error.type": exc_class,
        "error.stack_trace": stack,
    }


def fetch_logs_from_trino(config) -> List[dict]:
    """
    Run the configured Trino SQL and return a list of log docs for the pipeline.
    Requires TRINO_CLIENT_ID, TRINO_CLIENT_SECRET, and TRINO_SQL or TRINO_SQL_FILE.
    """
    if not config.trino_client_id or not config.trino_client_secret:
        raise ValueError("TRINO_CLIENT_ID and TRINO_CLIENT_SECRET are required.")

    token = get_trino_jwt(
        config.trino_client_id,
        config.trino_client_secret,
        config.trino_token_url,
    )
    sql = _resolve_sql(config)

    import sys
    print("Got JWT, connecting to Trino...", flush=True)
    sys.stdout.flush()
    with trino.dbapi.connect(
        host=config.trino_host,
        port=config.trino_port,
        catalog=config.trino_catalog,
        auth=JWTAuthentication(token),
        http_scheme="https",
        verify=config.trino_verify_ssl,
    ) as conn:
        cur = conn.cursor()
        print("Executing query (may take several minutes for large result sets)...", flush=True)
        sys.stdout.flush()
        cur.execute(sql)
        rows = cur.fetchall()
        print(f"Query complete, got {len(rows)} rows.", flush=True)
        sys.stdout.flush()
        col_names = [d[0] for d in cur.description] if cur.description else []

    return [_row_to_doc(row, col_names) for row in rows]


if __name__ == "__main__":
    """Run only the Trino fetch: get JWT, execute SQL, print doc count and first row."""
    import sys
    from config import Config

    print("Starting Trino fetch...", flush=True)
    sys.stdout.flush()
    docs = fetch_logs_from_trino(Config)
    print(f"Fetched {len(docs)} rows from Trino")
    if docs:
        print("First doc keys:", list(docs[0].keys()))
        print("First doc sample:")
        for k, v in docs[0].items():
            val = (v[:200] + "…") if isinstance(v, str) and len(v) > 200 else v
            print(f"  {k}: {val}")
    else:
        print("No rows returned.")
