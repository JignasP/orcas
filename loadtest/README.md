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
and the corresponding Grafana screenshots or queries with the report.
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
Do not report measurements until a live stack has been exercised.
