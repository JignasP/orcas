from concurrent.futures import ThreadPoolExecutor

from libs.orcas_common.runstore import InMemoryRunStore


def test_run_store_keeps_first_terminal_result_and_sequences_events():
    store = InMemoryRunStore()
    run_id = "20dedc07-67da-4770-82bd-83389b7f2004"
    store.create_run(run_id, {"text": "first"})
    store.create_run(run_id, {"text": "second"})
    assert store.get_run(run_id)["payload"] == {"text": "first"}

    store.update_status(run_id, "running")
    with ThreadPoolExecutor(max_workers=5) as pool:
        list(pool.map(lambda i: store.append_event(run_id, "system", "test", "tool_call", payload={"i": i}), range(25)))
    assert [event["seq"] for event in store.get_events(run_id)] == list(range(1, 26))

    accepted = {"status": "completed", "route": "assign_to_entity"}
    store.complete(run_id, accepted)
    store.complete(run_id, {"status": "escalated"})
    store.fail(run_id, "late retry")
    assert store.get_run(run_id)["result"] == accepted
    assert store.get_run(run_id)["status"] == "completed"


def test_quarantine_does_not_create_a_run():
    store = InMemoryRunStore()
    quarantine_id = store.quarantine({"text": "bad"}, "validation", [{"field": "text"}])
    assert store.get_quarantine(quarantine_id)["reason"] == "validation"
    assert store.runs == {}
