from libs.orcas_common.runstore import InMemoryRunStore
from services.worker.tasks import run_complaint_pipeline


class MustNotRun:
    def run(self, **_kwargs):
        raise AssertionError("completed run was executed again")


def test_duplicate_task_returns_existing_determination():
    store = InMemoryRunStore()
    run_id = "61950ddb-6b6b-4079-bdf5-bcf372158e42"
    store.create_run(run_id, {"text": "already processed"})
    store.complete(run_id, {"status": "completed", "run_id": run_id})
    result = run_complaint_pipeline(
        run_id, run_store=store, researcher_graph=MustNotRun(), verifier_graph=MustNotRun()
    )
    assert result == {"status": "completed", "run_id": run_id}
    assert store.get_events(run_id) == []
