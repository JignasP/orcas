import json

from services.llm_stub.app import ChatMessage, ChatRequest, generate_stub_reply


def test_stub_draft_cites_the_current_retrieved_chunk():
    ledger = [
        {"chunk_id": "sebi-current", "framework": "SEBI", "doc_id": "sebi_scores",
         "clause_id": "p1", "text": "Investor grievances for registered intermediaries."},
        {"chunk_id": "rbi-current", "framework": "RBI", "doc_id": "rbi_ombudsman",
         "clause_id": "p6", "doc_title": "RBI scheme", "circular_ref": "RBI-2021",
         "text": "Any customer aggrieved by deficiency in service may file a complaint."},
    ]
    prompt = "Complaint: My bank fixed deposit interest is wrong.\nEvidence Ledger: " + json.dumps(ledger)
    request = ChatRequest(messages=[ChatMessage(role="user", content=prompt)], step="draft")
    draft = json.loads(generate_stub_reply(request))
    assert draft["route"] == "refer_to_other_regulator"
    assert draft["citations"][0]["chunk_id"] == "rbi-current"
    assert draft["citations"][0]["quote_span"] in ledger[1]["text"]
    assert draft["timeline"] is None


def test_stub_draft_does_not_invent_a_citation_when_retrieval_is_empty():
    request = ChatRequest(
        messages=[ChatMessage(role="user", content="Complaint: My bank fixed deposit is wrong.\nEvidence Ledger: []")],
        step="draft",
    )
    draft = json.loads(generate_stub_reply(request))
    assert draft["citations"] == []
