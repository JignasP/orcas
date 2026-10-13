import json
import os
import uuid
import pytest
import jsonschema

from services.worker.agent.researcher import ResearcherGraph
from services.worker.agent.verifier import VerifierGraph
from services.worker.guardrails.output_filter import OutputFilter
from services.worker.clients.fake_retrieval import FakeRetrievalClient
from services.worker.clients.llm_client import LLMClient
from services.worker.clients.runstore import InMemoryRunStore
from services.worker.tasks import run_complaint_pipeline

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CONTRACT_PATH = os.path.join(BASE_DIR, "contracts", "determination.v1.schema.json")
FIXTURES_PATH = os.path.join(BASE_DIR, "tests", "fixtures", "retrieval_fixtures.json")

with open(CONTRACT_PATH, "r", encoding="utf-8") as f:
    DETERMINATION_SCHEMA = json.load(f)


@pytest.fixture
def fake_retrieval():
    return FakeRetrievalClient(fixtures_path=FIXTURES_PATH)


@pytest.fixture
def fake_llm():
    return LLMClient()


@pytest.fixture
def researcher_graph(fake_llm, fake_retrieval):
    return ResearcherGraph(llm_client=fake_llm, retrieval_client=fake_retrieval)


@pytest.fixture
def verifier_graph(fake_llm, fake_retrieval):
    return VerifierGraph(llm_client=fake_llm, retrieval_client=fake_retrieval)


def test_researcher_broker_complaint(researcher_graph, verifier_graph):
    """Test standard broker grievance routing to SEBI with valid schema."""
    run_id = str(uuid.uuid4())
    complaint = {
        "client_id": "test-client",
        "is_synthetic": True,
        "channel": "web",
        "date_of_event": "2026-08-01",
        "date_filed": "2026-09-01",
        "text": "My stock broker has not processed my withdrawal request for 45 days. I need immediate redressal."
    }

    result = run_complaint_pipeline(
        run_id=run_id,
        complaint_data=complaint,
        researcher_graph=researcher_graph,
        verifier_graph=verifier_graph
    )

    jsonschema.validate(instance=result, schema=DETERMINATION_SCHEMA)
    assert result["run_id"] == run_id
    assert result["status"] == "completed"
    assert result["disposed"] is False
    assert result["regulator"] == "SEBI"
    assert result["route"] == "assign_to_entity"
    assert len(result["citations"]) > 0
    assert result["verification"]["passed"] is True


def test_researcher_reference_case_4_1_bank_fd(researcher_graph, verifier_graph):
    """
    Test canonical §4.1 reference case:
    Bank Fixed Deposit grievance mentioning SEBI must swap framework to RBI and cite RBI Ombudsman Scheme.
    """
    run_id = str(uuid.uuid4())
    complaint = {
        "client_id": "test-client",
        "is_synthetic": True,
        "channel": "web",
        "date_of_event": "2026-08-01",
        "date_filed": "2026-09-01",
        "text": "I invested in a fixed deposit through my bank's app. The interest credited is lower than what I was promised. I want to complain to SEBI."
    }

    result = run_complaint_pipeline(
        run_id=run_id,
        complaint_data=complaint,
        researcher_graph=researcher_graph,
        verifier_graph=verifier_graph
    )

    jsonschema.validate(instance=result, schema=DETERMINATION_SCHEMA)
    assert result["run_id"] == run_id
    assert result["status"] == "completed"
    assert result["disposed"] is False
    assert result["regulator"] == "RBI"
    assert result["entity_type"] == "bank"
    assert result["route"] == "refer_to_other_regulator"
    assert len(result["citations"]) > 0
    assert result["citations"][0]["doc_id"] == "rbi_integrated_ombudsman_scheme_2021"
    assert result["verification"]["passed"] is True


def test_researcher_out_of_corpus_escalation(researcher_graph, verifier_graph):
    """Test out-of-corpus entity (e.g. Health Insurance) cleanly escalates to human without hallucinating."""
    run_id = str(uuid.uuid4())
    complaint = {
        "client_id": "test-client",
        "is_synthetic": True,
        "channel": "web",
        "date_of_event": "2026-08-01",
        "date_filed": "2026-09-01",
        "text": "My health insurer rejected my cashless hospitalization claim without justification."
    }

    result = run_complaint_pipeline(
        run_id=run_id,
        complaint_data=complaint,
        researcher_graph=researcher_graph,
        verifier_graph=verifier_graph
    )

    jsonschema.validate(instance=result, schema=DETERMINATION_SCHEMA)
    assert result["status"] == "escalated"
    assert result["route"] == "escalate_to_human"
    assert result["escalation"] is not None
    assert result["escalation"]["reason_code"] in ("out_of_corpus", "low_confidence")


def test_verifier_catches_unsupported_citation(researcher_graph, verifier_graph):
    """
    Test Demo Item #6:
    Planted bad citation causes Verifier to catch the discrepancy and escalate rather than rubber-stamp.
    """
    run_id = str(uuid.uuid4())
    complaint = {
        "client_id": "test-client",
        "is_synthetic": True,
        "channel": "web",
        "date_of_event": "2026-08-01",
        "date_filed": "2026-09-01",
        "text": "My stock broker refused to execute my trade."
    }

    result = run_complaint_pipeline(
        run_id=run_id,
        complaint_data=complaint,
        researcher_graph=researcher_graph,
        verifier_graph=verifier_graph,
        inject_bad_draft=True
    )

    jsonschema.validate(instance=result, schema=DETERMINATION_SCHEMA)
    assert result["status"] == "escalated"
    assert result["route"] == "escalate_to_human"
    assert result["verification"]["passed"] is False
    assert result["escalation"]["reason_code"] == "unverified"


def test_output_filter_blocks_forbidden_phrase():
    """Test guardrail blocks settlement language and enforces disposed=false."""
    bad_determination = {
        "run_id": str(uuid.uuid4()),
        "status": "completed",
        "route": "assign_to_entity",
        "regulator": "SEBI",
        "entity_type": "broker",
        "timeline": {"days": 30, "basis_citation_id": "c1"},
        "basis": "Your complaint resolved and compensation granted by the authority.",
        "citations": [],
        "escalation": None,
        "verification": {"passed": True, "claims_checked": 1, "claims_supported": 1, "attempts": 1},
        "prompt_versions": {},
        "index_version": "v1",
        "degraded": False,
        "disposed": True  # Invariant violation
    }

    is_safe, sanitized, msg = OutputFilter.filter(bad_determination)
    assert sanitized["disposed"] is False
    assert sanitized["status"] == "escalated"
    assert sanitized["route"] == "escalate_to_human"
    assert sanitized["escalation"]["reason_code"] == "guardrail"
