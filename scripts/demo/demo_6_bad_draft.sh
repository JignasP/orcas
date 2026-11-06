#!/usr/bin/env bash
# scripts/demo/demo_6_bad_draft.sh
# Demo #6: Planted bad citation causes Verifier to catch the discrepancy and trigger retry/escalation.
#
# Requirements: Demo #6, A3, F5
# Under Compose:
#   ORCAS_INJECT_BAD_DRAFT=1 docker compose up -d worker
#
# Expected trace:
#   researcher:draft -> verifier:verify (fails substring/ledger check) ->
#   verifier:retry (suggested_strategy emitted) -> researcher:draft (new search/re-draft) ->
#   verifier:verify -> accept or escalate (never rubber-stamps hallucinated citation)

set -euo pipefail

echo "================================================================="
echo "=== Demo #6: Planted Bad Citation & Verifier Retry Loop       ==="
echo "================================================================="
echo ""
echo "Running Demo #6 verification test..."
python -c '
import uuid, json, os
from services.worker.tasks import run_complaint_pipeline
from services.worker.clients.fake_llm import FakeLLMClient
from services.worker.clients.runstore import InMemoryRunStore
from services.worker.agent.researcher import ResearcherGraph
from services.worker.agent.verifier import VerifierGraph

store = InMemoryRunStore()
run_id = str(uuid.uuid4())
complaint = {
    "client_id": "demo-client-6",
    "is_synthetic": True,
    "channel": "web",
    "date_of_event": "2026-08-01",
    "date_filed": "2026-09-01",
    "text": "My stock broker refused to process my trade withdrawal."
}

llm = FakeLLMClient()
r = ResearcherGraph(llm_client=llm)
v = VerifierGraph(llm_client=llm)

res = run_complaint_pipeline(
    run_id=run_id,
    complaint_data=complaint,
    run_store=store,
    researcher_graph=r,
    verifier_graph=v,
    inject_bad_draft=True
)

events = store.get_events(run_id)
print("--- Emitted Run Events ---")
for ev in events:
    print(f"[{ev.get(\"agent\", \"-\")}:{ev.get(\"step\", \"-\")}] kind={ev.get(\"kind\")} payload={ev.get(\"payload\")}")

print("\n--- Final Determination ---")
print(json.dumps(res, indent=2))

assert any(ev.get("kind") == "retry" or ev.get("kind") == "verify" for ev in events)
assert res["verification"]["passed"] is False or res["status"] == "escalated"
print("\n✅ PASS: Planted bad draft caught by Verifier; rubber-stamping prevented.")
'

echo ""
echo "=== Demo #6 Complete ==="
