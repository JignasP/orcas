"""Capture queue and container resource samples for one load-test interval."""

from __future__ import annotations

import argparse
import json
import urllib.parse
import urllib.request


def query_range(base_url: str, expression: str, start: int, end: int) -> list[dict]:
    query = urllib.parse.urlencode({"query": expression, "start": start, "end": end, "step": 15})
    with urllib.request.urlopen(f"{base_url}/api/v1/query_range?{query}", timeout=15) as response:
        body = json.load(response)
    if body.get("status") != "success":
        raise ValueError(f"Prometheus query failed: {expression}: {body}")
    return body["data"]["result"]


def values(series: list[dict]) -> list[float]:
    return [float(value) for item in series for _, value in item.get("values", [])
            if value not in {"NaN", "+Inf", "-Inf"}]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("start", type=int)
    parser.add_argument("end", type=int)
    parser.add_argument("--prometheus-url", default="http://localhost:9090")
    args = parser.parse_args()
    base = args.prometheus_url.rstrip("/")
    queue = values(query_range(base, "orcas_celery_queue_depth", args.start, args.end))
    cpu = query_range(base, "sum by (name) (rate(container_cpu_usage_seconds_total"
                            "{name=~\".*orcas.*\"}[1m]))", args.start, args.end)
    memory = query_range(base, "container_memory_working_set_bytes"
                               "{name=~\".*orcas.*\"}", args.start, args.end)
    print(json.dumps({
        "start_unix": args.start,
        "end_unix": args.end,
        "queue_depth_max": max(queue) if queue else None,
        "queue_depth_mean": sum(queue) / len(queue) if queue else None,
        "queue_samples": len(queue),
        "cpu_cores_max_by_container": {
            item["metric"].get("name", "unknown"): max(samples)
            for item in cpu if (samples := values([item]))
        },
        "memory_bytes_max_by_container": {
            item["metric"].get("name", "unknown"): max(samples)
            for item in memory if (samples := values([item]))
        },
    }, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
