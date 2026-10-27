# Platform, reliability, and operations report material

## Architecture and boundaries

The FastAPI gateway owns validation, quarantine, rate limiting, cache lookup,
run creation, and Celery dispatch. Redis carries the Celery queue, short-lived
cache entries, and per-client token buckets. PostgreSQL stores run state,
ordered events, quarantine records, feedback, and verification scores. Worker
replicas run the Researcher and Verifier separately from intake. Retrieval owns
the embedded corpus index; the LLM gateway owns provider access and its shared
circuit breaker. [Architecture §2.1](../../ARCHITECTURE.md#21-deployment-boundaries-and-why)
documents why these are separate deployment units.

## Ingestion and safety

The gateway enforces the frozen complaint schema and cross-field date rules
before creating a run. Invalid JSON, malformed fields, and guardrail matches
are quarantined with a `422` response and do not dispatch a Celery task. The
input guardrail uses conservative instruction and threat patterns; the labelled
regression set includes 21 attack examples and 20 benign complaints. It flags
all labelled attacks and none of those 20 benign examples. This is a local
regression result, not a field false-positive estimate.

## Observability

All run IDs appear as correlation IDs in gateway, worker, retrieval, and LLM
gateway logs and HTTP headers. Run events record searches, passages, prompt
versions, LLM usage and cost, retries, verification, and terminal status.
Prometheus scrapes API metrics and a read-only worker metrics exporter.
Grafana dashboards are provisioned from versioned files. OpenTelemetry sends
traces to Jaeger through a collector. A live cross-service trace still needs
verification on a Docker host.

## SLO and experimental method

The target was committed before load testing: p95 submit-to-terminal latency
at most 90 seconds and at least 99% successful terminal outcomes with ten
concurrent clients, one worker container with two Celery processes, and a
1.5-second stub delay. [The SLO](../../slo.md) defines the complete workload.
Locust records the end-to-end observation separately from POST and poll times.
The same payload mix should be rerun at higher concurrency and then with
three worker replicas. Cache impact should be measured with repeated-input
and bypass modes at the same rate-limit setting.

## Results and limitations

No live Docker measurements are available from this machine. Fill in the
baseline and three-worker RPS, p50, p95, failure concurrency, limiting
component, cache hit ratio, cost per 100 runs, and controlled-failure outcomes
only after the documented experiments are executed. The stub's provider cost
is zero; do not present that as a production cost estimate.
