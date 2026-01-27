import argparse
import json
import os
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone

from elasticsearch import Elasticsearch

from config import Config
from llm_summary import summarize_report
from patch_proposal import propose_patch


@dataclass
class Cluster:
    key: str
    count: int
    error_type: str
    sample_message: str
    sample_stack: str
    sample_timestamp: str


def iso_now():
    return datetime.now(timezone.utc).isoformat()


def build_time_range(lookback_minutes):
    end = datetime.now(timezone.utc)
    start = end - timedelta(minutes=lookback_minutes)
    return start.isoformat(), end.isoformat()


def parse_stack_signature(stack_trace, max_frames=3):
    if not stack_trace:
        return ""
    lines = [line.strip() for line in stack_trace.splitlines()]
    frames = [line for line in lines if line.startswith("at ")]
    return " | ".join(frames[:max_frames])


def get_field(doc, dotted_key):
    parts = dotted_key.split(".")
    current = doc
    for part in parts:
        if isinstance(current, dict) and part in current:
            current = current[part]
        else:
            current = None
            break
    if current is not None:
        return current
    return doc.get(dotted_key)


def cluster_key(doc):
    error_type = get_field(doc, "error.type") or "UnknownError"
    stack_trace = get_field(doc, "error.stack_trace") or ""
    signature = parse_stack_signature(stack_trace)
    message = doc.get("message", "")
    if signature:
        return f"{error_type}::{signature}"
    return f"{error_type}::{message[:120]}"


def fetch_logs(es, index_pattern, start_ts, end_ts, size):
    query = {
        "query": {
            "bool": {
                "filter": [
                    {"range": {"@timestamp": {"gte": start_ts, "lte": end_ts}}},
                    {
                        "bool": {
                            "should": [
                                {"exists": {"field": "error.type"}},
                                {"exists": {"field": "error.stack_trace"}},
                                {"term": {"log.level": "ERROR"}},
                            ],
                            "minimum_should_match": 1,
                        }
                    },
                ]
            }
        },
        "sort": [{"@timestamp": {"order": "desc"}}],
        "size": size,
    }
    response = es.search(index=index_pattern, body=query)
    hits = response.get("hits", {}).get("hits", [])
    return [hit.get("_source", {}) for hit in hits]


def build_clusters(docs):
    clusters = defaultdict(list)
    for doc in docs:
        key = cluster_key(doc)
        clusters[key].append(doc)

    results = []
    for key, items in clusters.items():
        first = items[0]
        error_type = get_field(first, "error.type") or "UnknownError"
        results.append(
            Cluster(
                key=key,
                count=len(items),
                error_type=error_type,
                sample_message=first.get("message", ""),
                sample_stack=get_field(first, "error.stack_trace") or "",
                sample_timestamp=first.get("@timestamp", ""),
            )
        )
    results.sort(key=lambda c: c.count, reverse=True)
    return results


def summarize(docs, clusters):
    error_type_counts = Counter()
    for doc in docs:
        error_type_counts[get_field(doc, "error.type") or "UnknownError"] += 1
    return {
        "generated_at": iso_now(),
        "total_events": len(docs),
        "error_type_counts": error_type_counts.most_common(),
        "top_clusters": [asdict(c) for c in clusters[:10]],
    }


def write_report(output_dir, report):
    os.makedirs(output_dir, exist_ok=True)
    filename = f"report-{datetime.now().strftime('%Y%m%d-%H%M%S')}.json"
    path = os.path.join(output_dir, filename)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(report, handle, indent=2)
    return path


def main():
    parser = argparse.ArgumentParser(description="Auth service log analysis agent")
    parser.add_argument("--es-hosts", default=",".join(Config.es_hosts))
    parser.add_argument("--index-pattern", default=Config.index_pattern)
    parser.add_argument("--lookback-minutes", type=int, default=Config.lookback_minutes)
    parser.add_argument("--size", type=int, default=Config.query_size)
    parser.add_argument("--output-dir", default=Config.output_dir)
    args = parser.parse_args()

    es = Elasticsearch(args.es_hosts.split(","))
    start_ts, end_ts = build_time_range(args.lookback_minutes)
    docs = fetch_logs(es, args.index_pattern, start_ts, end_ts, args.size)
    clusters = build_clusters(docs)
    report = summarize(docs, clusters)
    report_path = write_report(args.output_dir, report)

    print(f"Fetched {len(docs)} events from {start_ts} to {end_ts}")
    print(f"Top clusters: {min(len(clusters), 10)}")
    print(f"Report written to {report_path}")

    summary_text, summary_error = summarize_report(report, Config)
    if summary_error:
        print(f"LLM summary skipped: {summary_error}")
    else:
        print("LLM summary generated (not written to file)")

    proposal_text, proposal_error = propose_patch(report, Config)
    if proposal_error:
        print(f"Patch proposal skipped: {proposal_error}")
    else:
        print("Patch proposal generated (not written to file)")


if __name__ == "__main__":
    main()

