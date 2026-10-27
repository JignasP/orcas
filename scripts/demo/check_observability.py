"""Verify provisioned dashboard and live Prometheus data after a demo run."""

from __future__ import annotations

import argparse
import json
import time
import urllib.parse
import urllib.request

REQUIRED_JOBS = {"gateway", "retrieval", "llm-gateway", "worker-metrics", "cadvisor"}
REQUIRED_SERIES = {"orcas_gateway_requests_total", "orcas_run_latency_seconds",
                   "orcas_celery_queue_depth"}


def read_json(url: str) -> dict:
    with urllib.request.urlopen(url, timeout=10) as response:
        return json.load(response)


def check(prometheus_url: str, grafana_url: str) -> tuple[set[str], int]:
    targets = read_json(f"{prometheus_url}/api/v1/targets?state=active")
    healthy_jobs = {
        target["labels"]["job"] for target in targets["data"]["activeTargets"]
        if target.get("health") == "up"
    }
    missing_jobs = REQUIRED_JOBS - healthy_jobs
    if missing_jobs:
        raise ValueError(f"Prometheus targets are not healthy: {sorted(missing_jobs)}")

    for series in REQUIRED_SERIES:
        query = urllib.parse.urlencode({"query": series})
        result = read_json(f"{prometheus_url}/api/v1/query?{query}")
        if not result.get("data", {}).get("result"):
            raise ValueError(f"Prometheus has no live {series} series")

    dashboard = read_json(f"{grafana_url}/api/dashboards/uid/orcas-platform")["dashboard"]
    if dashboard.get("uid") != "orcas-platform" or len(dashboard.get("panels", [])) < 21:
        raise ValueError("The ORCAS dashboard was not provisioned with its expected panels")
    for series in ("container_cpu_usage_seconds_total", "container_memory_working_set_bytes"):
        query = urllib.parse.urlencode({"query": series})
        result = read_json(f"{prometheus_url}/api/v1/query?{query}")
        samples = result.get("data", {}).get("result", [])
        ids = sorted(sample.get("metric", {}).get("id", "") for sample in samples)
        container_ids = [value for value in ids if "docker" in value or "containerd" in value]
        print(f"{series}: {len(samples)} series; sample labels: "
              f"{[sample.get('metric', {}) for sample in samples[:3]]}")
        print(f"{series}: {len(container_ids)} Docker/containerd cgroups; "
              f"examples: {container_ids[:5]}; all IDs: {ids}")
    return healthy_jobs, len(dashboard["panels"])


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--prometheus-url", default="http://localhost:9090")
    parser.add_argument("--grafana-url", default="http://localhost:3000")
    parser.add_argument("--timeout", type=int, default=90)
    args = parser.parse_args()
    deadline = time.monotonic() + args.timeout
    last_error = None
    while time.monotonic() < deadline:
        try:
            jobs, panels = check(args.prometheus_url.rstrip("/"), args.grafana_url.rstrip("/"))
            print(f"Live Prometheus targets: {', '.join(sorted(jobs))}; Grafana panels: {panels}")
            return 0
        except (OSError, KeyError, ValueError) as error:
            last_error = error
        time.sleep(3)
    raise SystemExit(f"Observability verification did not pass: {last_error}")


if __name__ == "__main__":
    raise SystemExit(main())
