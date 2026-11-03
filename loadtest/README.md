# End-to-end load test

The declared workload and target are in [docs/slo.md](../docs/slo.md).
`locustfile.py` submits synthetic complaints, polls to a terminal state, and
records a separate `ORCAS complaint_end_to_end` observation. That observation
includes queue time; the POST and GET rows are diagnostics only.

Run against a healthy stub-backed Compose stack:

```sh
python -m pip install -r loadtest/requirements.txt
mkdir -p loadtest/results
locust -f loadtest/locustfile.py --headless --host http://localhost:8000 \
  --users 10 --spawn-rate 2 --run-time 15m --csv loadtest/results/baseline
```

Repeat at higher user counts until the target fails, then use the same mix
and duration after `docker compose up --scale worker=3`. Preserve Locust CSVs
and the corresponding Grafana screenshots or queries with the CI artifacts.
Fixture `_` fields are removed before submission. Known injection scenarios
are excluded from the normal processing workload and should be tested
separately as expected `422` responses.

Each request gets a unique client ID, so the rate limit does not distort this
baseline. Cache comparisons require a separate repeated-input experiment.
Use `LOADTEST_CACHE_MODE=repeat` for repeated submissions and
`LOADTEST_CACHE_MODE=bypass` for the same submissions with cache bypassed.
Raise `RATE_LIMIT_PER_MIN` enough that neither comparison receives `429`,
warm the cache before recording, and compare the end-to-end p95, hit ratio,
and persisted cost per 100 runs. Record both settings with the results.

## Measured results

The [clean-runner benchmark](https://github.com/JignasP/orcas/actions/runs/40540516292)
used the 1.5-second LLM stub. Values below are submit-to-terminal Locust
observations; throughput is terminal outcomes per second.

| Workers | Clients | Observations | p50 | p95 | Throughput | Failures |
|---:|---:|---:|---:|---:|---:|---:|
| 1 | 10 | 363 | 23 s | 40 s | 0.387/s | 0 |
| 3 | 10 | 1,065 | 6.1 s | 20 s | 1.159/s | 0 |
| 1 | 20 | 130 | 47 s | 70 s | 0.376/s | 0 |
| 1 | 40 | 151 | 98 s | 123 s | 0.370/s | 0 |

The declared ten-client [SLO](../docs/slo.md) passed: p95 was below 90
seconds and all observations reached a successful terminal state. Forty
clients were the first tested load to breach the latency target. Escalated
outcomes count as successful terminal processing, not automated resolution.
Three worker replicas nearly tripled throughput at ten clients.

After cache warmup, 1,559 repeated-input observations had p95 0.32 seconds
and no new LLM calls in the database window. With bypass, 76 observations
had p95 42 seconds and 272 LLM calls. Four outcomes crossed the phase
boundary, so the database event count does not give an exact hit ratio for
the Locust observations. The stub's monetary cost was $0 per 100 runs in
both phases; these results do not estimate production savings. The artifact
contains Locust CSVs, logs, database snapshots, and `summary.json`.

To repeat the full sequence on a disposable stub-backed stack, run
`bash scripts/benchmarks/ci_experiment.sh` from the repository root after
the services are healthy.

The [resource ramp](https://github.com/JignasP/orcas/actions/workflows/load-ramp.yml)
also uploads Prometheus queue samples and per-phase Docker stats samples. Each
`*.docker-summary.json` reports the highest sampled CPU percentage and memory
usage by Compose container; samples are taken every ten seconds during Locust,
so they are sampled maxima rather than continuous peaks. CPU percentage follows
Docker's per-core convention and can exceed 100% on a multi-core host.
In the [measured ramp](https://github.com/JignasP/orcas/actions/runs/40900547182),
the 40-client queue peaked at 38, p95 reached 123 seconds, and the worker
reached 81.03% CPU and 289.1 MiB memory. Gateway and PostgreSQL peaked at
35.23% and 37.42% CPU. Queue growth and the scaling result point to limited
worker execution capacity. cAdvisor exposed host cgroups but no matching
Compose IDs on that fork runner, so the per-service figures use Docker stats.
