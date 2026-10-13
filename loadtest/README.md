# loadtest — payloads handoff (Tahir → Jignas)

`payloads.json` is the **final scenario payloads for load testing** (TAHIR.md handoff). Each entry
is a valid `complaint.v1` request body derived from `eval/scenarios.yaml` — the realistic mix of
complaints the system routes (bank FD, MF, broker, registrar, depository, RBI payment, split,
out-of-corpus, injection, ambiguous).

Jignas owns the Locust driver and SLO; this directory just provides the request bodies. Example:
```python
import json, random
PAYLOADS = json.load(open("loadtest/payloads.json"))["payloads"]
# in a Locust task: self.client.post("/v1/complaints", json=random.choice(PAYLOADS))
```
Dates are fixed and valid (`date_filed ≥ date_of_event`, not in the future) and `is_synthetic` is
true. Malformed/guardrail payloads for the rejection tests are Jignas's to author.
