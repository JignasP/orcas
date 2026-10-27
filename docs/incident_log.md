# Incident log

Record only observed development or demo failures. For each entry include UTC
time, affected service, symptom, detection, cause, recovery, and follow-up.

## 2026-10-27 04:27 UTC — Celery task missing in Compose smoke run

- **Affected service:** worker in the stub-backed GitHub Actions Compose stack.
- **Symptom:** a valid complaint stayed queued until the 180-second demo timeout.
  The worker was healthy enough to answer Celery pings but discarded
  `orcas.run_complaint` as an unregistered task.
- **Detection:** the `compose-smoke` job for commit `134fe2f` failed while polling
  run `151e64fd-6b0b-494d-9434-c5292017f141`; worker logs identified the
  unregistered task.
- **Cause:** worker tracing setup imported FastAPI instrumentation although the
  worker image does not install FastAPI. A broad `ImportError` handler then
  suppressed that failure before the task decorator ran.
- **Recovery:** commit `5672df4` loads FastAPI instrumentation only for HTTP
  services and makes unexpected worker import errors fail startup. An isolated
  regression test confirms task registration without FastAPI. The repeat
  [Compose smoke run](https://github.com/Mitxh13/orcas/actions/runs/40450433329)
  passed: run `d3a61367-dc35-4f2f-8639-624f2ba49704` completed with the RBI
  route, and the malformed request returned quarantine ID
  `78a85f7e-b737-4f74-9b7b-1fa5d8fe024e`.
- **Follow-up:** keep the full-stack intake smoke test in CI. The controlled
  worker, Redis, and retrieval failure checks in the [runbook](runbook.md)
  still need to be run.
