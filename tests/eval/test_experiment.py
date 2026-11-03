"""Pre-registered agent experiments (T3): registry, comparison, and per-config runs."""
import json
import subprocess
from types import SimpleNamespace

from eval import experiment


def _results(tag, prompts, **overall):
    base = {"n_scenarios": 22, "n_answered": 10, "groundedness": 0.8, "context_relevance": 0.5,
            "faithfulness": 0.8, "hallucination_rate": 0.3, "route_accuracy": 0.5,
            "regulator_accuracy": 0.5, "entity_accuracy": 0.5, "escalation_precision": 0.5,
            "escalation_recall": 0.5, "supporting_passage_retrieved": 0.2,
            "supporting_passage_cited": 0.1, "judge": "embedding", "judge_thresholds": {}}
    base.update(overall)
    return {"tag": tag, "sut": "agent", "models": ["m"], "prompt_versions": prompts,
            "index_versions": ["iv"], "overall": base, "per_scenario": [{"llm_calls": 5}] * 22}


SPEC = {"requirement": "L2", "change": "reflect v1 vs v2", "hypothesis": "h",
        "primary_metric": "route_accuracy",
        "configs": {"before": {"PROMPT_RESEARCHER_REFLECT": "v1"},
                    "after": {"PROMPT_RESEARCHER_REFLECT": "v2"}}}


def test_registry_preregisters_hypothesis_metric_and_two_configs():
    specs = experiment.load_experiments()
    assert {"l2-reflect-prompt", "l3-cite-by-evidence-number"} <= set(specs)
    for spec in specs.values():
        assert spec["hypothesis"].strip() and spec["requirement"] in {"L2", "L3"}
        assert len(spec["configs"]) == 2
        assert spec["primary_metric"] in (experiment.RAG_METRICS + experiment.LABEL_METRICS
                                          + experiment.PASSAGE_METRICS)


def test_compare_reports_all_four_metrics_and_scenario_delta():
    report = experiment.compare(
        "l2", SPEC, _results("b", ["researcher_reflect:v1"]),
        _results("a", ["researcher_reflect:v2"], route_accuracy=0.682, groundedness=0.85))
    metrics = {r["metric"]: r for r in report["table"]}
    assert set(experiment.RAG_METRICS) <= set(metrics)
    assert metrics["groundedness"]["delta"] == 0.05
    assert "+4 of 22 scenarios" in report["verdict"]
    assert report["warnings"] == [] and report["after"]["llm_calls"] == 110


def test_compare_flags_small_deltas_and_ineffective_overrides():
    same = ["researcher_reflect:v2"]
    report = experiment.compare("l2", SPEC, _results("b", same),
                                _results("a", same, route_accuracy=0.545))
    assert "within noise" in report["verdict"]
    assert any("override had no effect" in w for w in report["warnings"])


def test_run_evaluates_each_config_in_a_fresh_process_with_its_overrides(tmp_path, monkeypatch):
    monkeypatch.setattr(experiment, "RESULTS", tmp_path)
    monkeypatch.setattr(experiment, "load_experiments", lambda: {"l2": SPEC})
    seen = []

    def fake_run(cmd, env, check, cwd):
        tag = cmd[cmd.index("--tag") + 1]
        seen.append((tag, env["PROMPT_RESEARCHER_REFLECT"]))
        version = env["PROMPT_RESEARCHER_REFLECT"]
        (tmp_path / f"{tag}.json").write_text(json.dumps(
            _results(tag, [f"researcher_reflect:{version}"])))
        return subprocess.CompletedProcess(cmd, 0)

    monkeypatch.setattr(experiment.subprocess, "run", fake_run)
    args = SimpleNamespace(name="l2", llm="gateway", sleep=0.0, retrieval_url=None, allow_stub=False)
    assert experiment.cmd_run(args) == 0
    assert seen == [("exp-l2-before", "v1"), ("exp-l2-after", "v2")]
    assert json.loads((tmp_path / "exp-l2.json").read_text())["primary_metric"] == "route_accuracy"


def test_run_refuses_stub_for_experiments_that_need_a_live_model(monkeypatch):
    monkeypatch.setattr(experiment, "load_experiments",
                        lambda: {"l2": {**SPEC, "needs_live_model": True}})
    args = SimpleNamespace(name="l2", llm="stub", sleep=0.0, retrieval_url=None, allow_stub=False)
    assert experiment.cmd_run(args) == 2
