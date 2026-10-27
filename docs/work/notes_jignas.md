# Jignas implementation notes

## 2026-10-26 — Initial demo path

- Added a shared run-store interface with in-memory and Postgres implementations.
  The first migration creates `runs`, `run_events`, `quarantine`, `feedback`,
  and `eval_scores`.
- Added the real FastAPI gateway. It validates the frozen complaint fields and
  cross-field date rules before creating a run or sending a Celery task. Rejected
  bodies receive field-level errors and a persisted quarantine ID.
- Connected the worker to the shared store and retrieval HTTP API when those
  services are configured. Duplicate terminal runs return their existing result.
- Added the initial Compose stack and corrected the service image build paths.
  The LLM stub is the default for the first demo. Its draft citations now come
  from the current retrieval evidence rather than old fixture IDs.
- Added an initial demo script and a guide for showing a valid run and a
  quarantined malformed request.

**Checks performed:** platform and agent tests passed locally; the Postgres
migration was applied twice to a temporary PostgreSQL 17 database, and the
database-backed intake test passed. Docker is not installed on this machine, so
the Compose stack has not yet been started here. A clean-clone run on a Docker
host remains the release gate for the initial demo.

## 2026-10-27 — Reliability and operations work

- Added pre-enqueue prompt-injection and explicit-threat checks for both free-text
  fields. The labelled regression set has 21 attack examples and 20 benign
  complaints; no benign examples were flagged in that set.
- Added protected quarantine review, persisted feedback and verification
  scores, ordered run trace responses, a Redis token bucket, and a completed-run
  cache versioned by input, retrieval index, and prompt file contents.
- Declared the stub-backed 90-second p95 target in `docs/slo.md` before adding
  the Locust driver. The driver measures submit-to-terminal latency and has
  separate cache comparison modes.
- Added correlated HTTP headers and JSON logging for gateway, retrieval, and
  LLM gateway, plus persisted retrieval/LLM events from the worker. Added
  OTLP→collector→Jaeger configuration and file-provisioned Prometheus/Grafana.
- Added a read-only worker metrics exporter for queue depth, run latency,
  status, cost, tokens, feedback, and verification scores.

**Checks performed:** platform/agent/web tests, targeted metrics and adapter
tests, Ruff, and YAML/JSON parsing. Docker is still unavailable locally, so
Compose startup, a cross-service Jaeger trace, load/scaling numbers, and
controlled failure checks remain unverified. No performance or cost result has
been inferred from the static checks.
