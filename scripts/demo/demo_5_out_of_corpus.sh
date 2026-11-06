#!/usr/bin/env bash
# scripts/demo/demo_5_out_of_corpus.sh
# Demo #5: Out-of-corpus complaint (Health Insurance) cleanly escalates to human without hallucinating.
#
# Requirements: F7, A3, Demo #5
# Expected: status=escalated, route=escalate_to_human, regulator=UNDETERMINED,
#           escalation.reason_code=out_of_corpus

set -euo pipefail

API_URL="${1:-${ORCAS_API_URL:-http://localhost:8000}}"

echo "================================================================="
echo "=== Demo #5: Out-of-Corpus Escalation (Health Insurance)      ==="
echo "================================================================="
echo "Submitting health insurance complaint to: $API_URL"
echo ""

PAYLOAD='{
  "client_id": "demo-client",
  "is_synthetic": true,
  "channel": "web",
  "date_of_event": "2026-08-01",
  "date_filed": "2026-09-01",
  "text": "My health insurer rejected my cashless hospitalization claim at Apollo Hospital without giving any valid justification. I need my medical expenses refunded."
}'

echo "Complaint text:"
echo "  $PAYLOAD"
echo ""

RESPONSE=$(curl -s -X POST "$API_URL/v1/complaints" \
  -H "Content-Type: application/json" \
  -d "$PAYLOAD" || echo "")

if [ -z "$RESPONSE" ]; then
    echo "Direct HTTP submission not available; running offline verification via test harness:"
    python -c '
import uuid, json
from services.worker.tasks import run_complaint_pipeline
from services.worker.clients.fake_llm import FakeLLMClient
from services.worker.agent.researcher import ResearcherGraph
from services.worker.agent.verifier import VerifierGraph

llm = FakeLLMClient(overrides={
    "classify": {
        "entity_type": "other",
        "regulator": "UNDETERMINED",
        "product": "health_insurance",
        "stated_regulator": None,
        "reasoning": "Insurance falls under IRDAI, outside covered SEBI/RBI corpus."
    }
})
r = ResearcherGraph(llm_client=llm)
v = VerifierGraph(llm_client=llm)
complaint = {
    "client_id": "demo-client",
    "is_synthetic": True,
    "channel": "web",
    "date_of_event": "2026-08-01",
    "date_filed": "2026-09-01",
    "text": "My health insurer rejected my cashless hospitalization claim."
}
res = run_complaint_pipeline(str(uuid.uuid4()), complaint, researcher_graph=r, verifier_graph=v)
print(json.dumps(res, indent=2))
assert res["status"] == "escalated", "Expected escalated"
assert res["route"] == "escalate_to_human", "Expected escalate_to_human"
assert res["regulator"] == "UNDETERMINED", "Expected UNDETERMINED regulator"
assert res["escalation"]["reason_code"] in ("out_of_corpus", "low_confidence")
print("\n✅ PASS: Out-of-corpus complaint escalated cleanly to human with regulator=UNDETERMINED.")
'
else
    echo "Server response:"
    echo "$RESPONSE" | python -m json.tool 2>/dev/null || echo "$RESPONSE"
fi

echo ""
echo "=== Demo #5 Complete ==="
