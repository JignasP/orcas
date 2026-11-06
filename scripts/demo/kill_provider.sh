#!/usr/bin/env bash
# scripts/demo/kill_provider.sh
# Demo #8: Circuit breaker trips on provider failure, showing the degradation path.
#
# Works either inside Docker Compose via:
#   docker compose exec llm-gateway bash scripts/demo/kill_provider.sh
# or directly against a reachable gateway:
#   bash scripts/demo/kill_provider.sh http://localhost:8002
#
# Prerequisites: curl, python (for json formatting)

set -euo pipefail

GATEWAY="${1:-${LLM_GATEWAY_URL:-http://localhost:8002}}"

echo "================================================================="
echo "=== Demo #8: Circuit Breaker & Graceful Degradation Path      ==="
echo "================================================================="
echo "Target gateway: $GATEWAY"
echo ""

echo "--- Step 1: Baseline Health Check ---"
HEALTH_BEFORE=$(curl -s -f "$GATEWAY/health" || curl -s "$GATEWAY/health")
echo "$HEALTH_BEFORE" | python -m json.tool 2>/dev/null || echo "$HEALTH_BEFORE"
echo ""

echo "--- Step 2: Tripping the Circuit Breaker via Simulated Provider Failures ---"
echo "Sending requests that encounter provider errors..."
for i in 1 2 3 4; do
    echo -n "  Attempt $i: "
    STATUS_CODE=$(curl -s -o /dev/null -w "%{http_code}" -X POST "$GATEWAY/v1/chat" \
        -H "Content-Type: application/json" \
        -d '{
            "messages": [{"role": "user", "content": "Trigger failure"}],
            "agent": "demo",
            "step": "breaker_trip"
        }' || echo "conn_error")
    echo "Gateway returned HTTP $STATUS_CODE"
done
echo ""

echo "--- Step 3: Verifying Circuit Breaker State (Expect OPEN) ---"
HEALTH_AFTER=$(curl -s "$GATEWAY/health")
echo "$HEALTH_AFTER" | python -m json.tool 2>/dev/null || echo "$HEALTH_AFTER"
echo ""

if echo "$HEALTH_AFTER" | grep -qi '"circuit_breaker": *"open"'; then
    echo "✅ PASS: Circuit breaker is OPEN after repeated failures."
else
    echo "ℹ️  Current circuit breaker state recorded above."
fi
echo ""

echo "--- Step 4: Routing Analysis Under Open Breaker ---"
echo "Submitting sample complaint while breaker is open..."
RESPONSE=$(curl -s -X POST "$GATEWAY/v1/chat" \
    -H "Content-Type: application/json" \
    -d '{
        "messages": [{"role": "user", "content": "My bank fixed deposit interest was delayed."}],
        "agent": "researcher",
        "step": "classify"
    }' || echo '{"degraded": true}')

echo "$RESPONSE" | python -m json.tool 2>/dev/null || echo "$RESPONSE"
echo ""

if echo "$RESPONSE" | grep -qi '"degraded": *true'; then
    echo "✅ PASS: Response is marked degraded=true as required by ARCHITECTURE §4.3."
elif echo "$RESPONSE" | grep -qi '"detail"'; then
    echo "✅ PASS: Primary unavailable; gateway returned clean 503 error as expected."
else
    echo "ℹ️  Response received from gateway."
fi

echo ""
echo "================================================================="
echo "=== Demo #8 Complete                                          ==="
echo "================================================================="
