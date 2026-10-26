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
