"""Tests for ``okfsmith eval`` (P4): golden sets, RAG Triad heuristics,
retrieval-vs-generation diagnosis, CI gating, JSON shape, malformed golden
files, and temporal interplay.

All LLM-judge paths are tested with fake backends — no network, no keys.
The ``--no-llm`` heuristic path is fully deterministic (shared BM25 engine
+ stdlib token overlap), so fixture-bundle runs assert exact diagnoses.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from okfsmith import eval as E
from okfsmith.cli.app import app
from okfsmith.core import Bundle, frontmatter

runner = CliRunner()
WIDE = {"COLUMNS": "200"}


# ---------------------------------------------------------------------------
# Fixture builders
# ---------------------------------------------------------------------------


def _concept_md(fm: dict, body: str) -> str:
    return frontmatter.serialize_frontmatter(fm, body)


def _write_bundle(root: Path, concepts: dict[str, tuple[dict, str]]) -> Path:
    """Write a minimal bundle: {concept_id: (frontmatter, body)}."""
    root.mkdir(parents=True, exist_ok=True)
    for cid, (fm, body) in concepts.items():
        path = root / f"{cid}.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(_concept_md(fm, body), encoding="utf-8")
    return root


def _write_golden(root: Path, records: list[dict]) -> Path:
    path = root / "eval" / "golden.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(records), encoding="utf-8")
    return path


def _good_bundle(tmp_path: Path) -> Path:
    """Two-concept bundle where one question retrieves cleanly."""
    bdir = _write_bundle(
        tmp_path / "kb",
        {
            "policies/refunds": (
                {
                    "type": "Policy",
                    "title": "Refund policy",
                    "description": "Customers get a full refund within 30 days.",
                },
                "The refund policy states that customers get a full refund "
                "within 30 days of purchase. Contact support to start a "
                "refund request.\n",
            ),
            "policies/shipping": (
                {
                    "type": "Policy",
                    "title": "Shipping policy",
                    "description": "Orders ship within 2 business days.",
                },
                "Orders ship within 2 business days via tracked courier.\n",
            ),
        },
    )
    _write_golden(
        bdir,
        [
            {
                "id": "refund-window",
                "question": "How long do customers have to request a refund?",
                "expected_answer": "Customers get a full refund within 30 days.",
                "must_cite": ["policies/refunds"],
                "tags": ["policy"],
            }
        ],
    )
    return bdir


# ---------------------------------------------------------------------------
# Golden schema validation
# ---------------------------------------------------------------------------


class TestGoldenSchema:
    def _load(self, tmp_path: Path, payload) -> list[E.GoldenQuestion]:
        bdir = tmp_path / "kb"
        path = bdir / "eval" / "golden.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            payload if isinstance(payload, str) else json.dumps(payload),
            encoding="utf-8",
        )
        return E.load_golden_set(bdir)

    def test_valid_minimal_defaults(self, tmp_path):
        questions = self._load(
            tmp_path, [{"id": "q1", "question": "What?"}]
        )
        assert len(questions) == 1
        assert questions[0].expected_answer == ""
        assert questions[0].must_cite == []
        assert questions[0].tags == []

    def test_valid_full(self, tmp_path):
        questions = self._load(
            tmp_path,
            [
                {
                    "id": "q1",
                    "question": "What?",
                    "expected_answer": "This.",
                    "must_cite": ["a/b"],
                    "tags": ["t"],
                }
            ],
        )
        assert questions[0].must_cite == ["a/b"]
        assert questions[0].tags == ["t"]

    def test_questions_wrapper_accepted(self, tmp_path):
        questions = self._load(
            tmp_path, {"questions": [{"id": "q1", "question": "What?"}]}
        )
        assert len(questions) == 1

    def test_missing_file(self, tmp_path):
        with pytest.raises(E.EvalError) as excinfo:
            E.load_golden_set(tmp_path / "kb")
        assert excinfo.value.code == "golden-not-found"

    def test_malformed_json_reports_line(self, tmp_path):
        with pytest.raises(E.EvalError) as excinfo:
            self._load(tmp_path, '[{"id": "q1", oops]')
        assert excinfo.value.code == "golden-invalid"
        assert "line" in excinfo.value.message

    @pytest.mark.parametrize(
        "payload",
        [
            {"id": "q1"},  # not a list
            [],  # empty
            [{"question": "no id"}],  # missing id
            [{"id": "q1"}],  # missing question
            [{"id": "q1", "question": 42}],  # question not a string
            [{"id": "q1", "question": "Q", "expected_answer": 7}],
            [{"id": "q1", "question": "Q", "must_cite": "a/b"}],  # not a list
            [{"id": "q1", "question": "Q", "must_cite": [1]}],
            [{"id": "q1", "question": "Q", "tags": "t"}],
            [{"id": "q1", "question": "Q"}, {"id": "q1", "question": "dup"}],
            ["not-an-object"],
        ],
    )
    def test_schema_violations(self, tmp_path, payload):
        with pytest.raises(E.EvalError) as excinfo:
            self._load(tmp_path, payload)
        assert excinfo.value.code == "golden-schema"


# ---------------------------------------------------------------------------
# Heuristic metrics: deterministic on a fixture bundle
# ---------------------------------------------------------------------------


class TestHeuristicMetrics:
    def _run(self, tmp_path: Path) -> E.EvalReport:
        bdir = _good_bundle(tmp_path)
        bundle = Bundle.load(bdir)
        return E.run_eval(bundle, bdir, no_llm=True)

    def test_deterministic_and_heuristic_labeled(self, tmp_path):
        first = self._run(tmp_path)
        second = self._run(tmp_path)
        assert first.as_dict() == second.as_dict()
        assert first.judge_mode == "heuristic"
        question = first.questions[0]
        assert question.passed
        assert question.diagnosis is None
        for score in question.scores.values():
            assert score.method == "heuristic"
            assert 0.0 <= score.value <= 1.0

    def test_scores_match_unit_heuristics(self, tmp_path):
        bdir = _good_bundle(tmp_path)
        bundle = Bundle.load(bdir)
        concepts = list(bundle.iter_concepts())
        golden = E.load_golden_set(bdir)[0]
        ctx, _ = E.heuristic_context_relevancy(
            golden.question, golden.expected_answer, concepts
        )
        assert ctx == 1.0  # both concepts share vocabulary with the question
        answer, cited = E.extractive_answer(concepts)
        assert "policies/refunds" in cited
        faith, _ = E.heuristic_faithfulness(answer, concepts)
        assert faith == 1.0  # excerpts come from the context itself
        ans, _ = E.heuristic_answer_relevancy(golden.question, answer)
        assert ans >= 0.4  # above the default answer-relevancy bar

    def test_empty_retrieval_scores_zero(self):
        value, _ = E.heuristic_context_relevancy("q", "a", [])
        assert value == 0.0
        value, _ = E.heuristic_faithfulness("", [])
        assert value == 0.0


# ---------------------------------------------------------------------------
# Retrieval-vs-generation diagnosis
# ---------------------------------------------------------------------------


class TestDiagnosis:
    def _question(self, must_cite):
        return E.GoldenQuestion(
            id="q", question="Q", expected_answer="A", must_cite=must_cite
        )

    def test_no_failures_no_diagnosis(self):
        diagnosis, reason = E.diagnose(self._question(["a"]), ["a"], True, [])
        assert diagnosis is None
        assert reason == ""

    def test_missing_must_cite_is_retrieval(self):
        diagnosis, reason = E.diagnose(
            self._question(["policies/refunds"]),
            ["policies/shipping"],
            True,
            ["faithfulness"],
        )
        assert diagnosis == "retrieval"
        assert "policies/refunds" in reason

    def test_nothing_relevant_is_retrieval(self):
        diagnosis, _ = E.diagnose(
            self._question([]), ["policies/shipping"], False, ["context_relevancy"]
        )
        assert diagnosis == "retrieval"

    def test_retrieved_but_wrong_is_generation(self):
        diagnosis, reason = E.diagnose(
            self._question(["policies/refunds"]),
            ["policies/refunds"],
            True,
            ["answer_relevancy"],
        )
        assert diagnosis == "generation"
        assert "answer_relevancy" in reason

    def test_end_to_end_retrieval_failure(self, tmp_path):
        """must_cite concept shares no vocabulary -> not retrieved."""
        bdir = _write_bundle(
            tmp_path / "kb",
            {
                "zoo/giraffe": (
                    {"type": "Animal", "title": "Giraffe"},
                    "Giraffes are tall savanna mammals with long necks.\n",
                ),
            },
        )
        _write_golden(
            bdir,
            [
                {
                    "id": "quantum",
                    "question": "Explain quantum entanglement decoherence",
                    "expected_answer": "Entangled particles lose coherence.",
                    "must_cite": ["zoo/giraffe"],
                }
            ],
        )
        report = E.run_eval(Bundle.load(bdir), bdir, no_llm=True)
        question = report.questions[0]
        assert not question.passed
        assert question.diagnosis == "retrieval"
        assert question.missing_must_cite == ["zoo/giraffe"]
        assert question.retrieved_ids == []

    def test_unretrieved_must_cite_fails_even_when_scores_pass(self, tmp_path):
        """Phantom must_cite id: metrics pass, the question still fails."""
        bdir = _good_bundle(tmp_path)
        _write_golden(
            bdir,
            [
                {
                    "id": "phantom",
                    "question": "How long do customers have to request a refund?",
                    "expected_answer": "Customers get a full refund within 30 days.",
                    "must_cite": ["concepts/phantom-widget"],
                }
            ],
        )
        report = E.run_eval(Bundle.load(bdir), bdir, no_llm=True)
        question = report.questions[0]
        assert not question.passed
        assert question.diagnosis == "retrieval"
        assert question.missing_must_cite == ["concepts/phantom-widget"]
        assert "must_cite" in question.failing_metrics

    def test_end_to_end_generation_failure(self, tmp_path):
        """Concept retrieved, but the answer misses the question's terms."""
        bdir = _write_bundle(
            tmp_path / "kb",
            {
                "policies/refunds": (
                    {
                        "type": "Policy",
                        "title": "Refund policy",
                        "description": "Customers get a full refund within 30 days.",
                    },
                    "The refund policy states that customers get a full "
                    "refund within 30 days of purchase.\n",
                ),
            },
        )
        _write_golden(
            bdir,
            [
                {
                    "id": "flibber",
                    # "flibbertigibbet jurisprudence" matches nothing in the
                    # answer excerpt -> answer_relevancy fails, but "refund"
                    # still retrieves the concept.
                    "question": "What is the flibbertigibbet jurisprudence "
                    "on refund timelines?",
                    "expected_answer": "Refunds within 30 days.",
                    "must_cite": ["policies/refunds"],
                }
            ],
        )
        report = E.run_eval(Bundle.load(bdir), bdir, no_llm=True)
        question = report.questions[0]
        assert not question.passed
        assert question.diagnosis == "generation"
        assert "policies/refunds" in question.retrieved_ids
        assert "answer_relevancy" in question.failing_metrics


# ---------------------------------------------------------------------------
# LLM judge plumbing (fake backends — no network)
# ---------------------------------------------------------------------------


class _FakeJudge:
    """Backend returning canned judge JSON."""

    def __init__(self, payload):
        self.payload = payload

    def chat(self, messages, **kwargs):
        return json.dumps(self.payload)


class _BrokenJudge:
    def chat(self, messages, **kwargs):
        raise RuntimeError("boom")


class TestLLMJudge:
    def _concepts(self, tmp_path):
        bdir = _good_bundle(tmp_path)
        return list(Bundle.load(bdir).iter_concepts())

    def test_judge_labels_llm_judge(self, tmp_path):
        concepts = self._concepts(tmp_path)
        score = E.judge_context_relevancy(
            _FakeJudge({"relevant": ["policies/refunds", "policies/shipping"]}),
            "refund question",
            "refund answer",
            concepts,
        )
        assert score.method == "llm-judge"
        assert score.value == 1.0

    def test_judge_faithfulness_parses_claims(self, tmp_path):
        concepts = self._concepts(tmp_path)
        score = E.judge_faithfulness(
            _FakeJudge(
                {
                    "claims": [
                        {"claim": "a", "supported": True},
                        {"claim": "b", "supported": False},
                    ]
                }
            ),
            "Some answer.",
            concepts,
        )
        assert score.method == "llm-judge"
        assert score.value == 0.5

    def test_judge_answer_relevancy(self, tmp_path):
        score = E.judge_answer_relevancy(
            _FakeJudge({"score": 0.75, "reason": "on topic"}), "Q", "A"
        )
        assert score.method == "llm-judge"
        assert score.value == 0.75

    def test_judge_failure_degrades_to_heuristic(self, tmp_path):
        concepts = self._concepts(tmp_path)
        score = E.judge_context_relevancy(
            _BrokenJudge(), "refund question", "refund answer", concepts
        )
        assert score.method == "heuristic"
        assert "judge failed" in score.detail

    def test_mixed_mode_when_judge_partially_fails(self, tmp_path):
        # A backend whose JSON is garbage for every metric -> all heuristic.
        bdir = _good_bundle(tmp_path)
        bundle = Bundle.load(bdir)
        golden = E.load_golden_set(bdir)[0]
        result = E.score_question(
            bundle,
            golden,
            top_k=5,
            metric_thresholds=dict(E.DEFAULT_THRESHOLDS),
            backend=_BrokenJudge(),
            as_of=None,
            include_superseded=False,
        )
        assert all(s.method == "heuristic" for s in result.scores.values())

    def test_all_judge_calls_failing_is_heuristic_mode(
        self, tmp_path, monkeypatch
    ):
        # A configured backend whose every judge call fails must label the
        # run "heuristic", not "mixed".
        bdir = _good_bundle(tmp_path)
        monkeypatch.setattr(
            E, "_resolve_judge_backend", lambda **kwargs: _BrokenJudge()
        )
        report = E.run_eval(Bundle.load(bdir), bdir)
        assert report.judge_mode == "heuristic"
        assert all(
            score.method == "heuristic"
            for question in report.questions
            for score in question.scores.values()
        )

    def test_all_judge_calls_succeeding_is_llm_judge_mode(
        self, tmp_path, monkeypatch
    ):
        bdir = _good_bundle(tmp_path)
        payload = {
            "relevant": ["policies/refunds", "policies/shipping"],
            "claims": [{"claim": "x", "supported": True}],
            "score": 0.9,
            "reason": "on topic",
        }
        monkeypatch.setattr(
            E,
            "_resolve_judge_backend",
            lambda **kwargs: _FakeJudge(payload),
        )
        report = E.run_eval(Bundle.load(bdir), bdir)
        assert report.judge_mode == "llm-judge"
        assert all(
            score.method == "llm-judge"
            for question in report.questions
            for score in question.scores.values()
        )


# ---------------------------------------------------------------------------
# CLI: exit codes, JSON shape, malformed files, --init-sample
# ---------------------------------------------------------------------------


class TestEvalCLI:
    def test_missing_golden_is_clean_error(self, tmp_path):
        bdir = tmp_path / "kb"
        bdir.mkdir()
        (bdir / "a.md").write_text(
            _concept_md({"type": "Note"}, "hello\n"), encoding="utf-8"
        )
        result = runner.invoke(app, ["eval", str(bdir), "--no-llm"], env=WIDE)
        assert result.exit_code == 1
        assert "error [golden-not-found]" in result.output
        assert "Traceback" not in result.output

    def test_malformed_golden_is_clean_error_json(self, tmp_path):
        bdir = tmp_path / "kb"
        bdir.mkdir()
        (bdir / "a.md").write_text(
            _concept_md({"type": "Note"}, "hello\n"), encoding="utf-8"
        )
        path = bdir / "eval" / "golden.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('[{"id": broken]', encoding="utf-8")
        result = runner.invoke(
            app, ["eval", str(bdir), "--no-llm", "--format", "json"], env=WIDE
        )
        assert result.exit_code == 1
        payload = json.loads(result.output)
        assert payload["status"] == "error"
        assert payload["code"] == "golden-invalid"

    def test_schema_violation_is_clean_error(self, tmp_path):
        bdir = _good_bundle(tmp_path)
        _write_golden(bdir, [{"id": "q"}])  # missing question
        result = runner.invoke(app, ["eval", str(bdir), "--no-llm"], env=WIDE)
        assert result.exit_code == 1
        assert "error [golden-schema]" in result.output
        assert "Traceback" not in result.output

    def test_ci_gate_exit_codes(self, tmp_path):
        bdir = _good_bundle(tmp_path)
        passing = runner.invoke(
            app, ["eval", str(bdir), "--no-llm", "--fail-under", "0"], env=WIDE
        )
        assert passing.exit_code == 0
        failing = runner.invoke(
            app, ["eval", str(bdir), "--no-llm", "--fail-under", "100"], env=WIDE
        )
        assert failing.exit_code == 1
        assert "CI gate" in failing.output

    def test_usage_errors(self, tmp_path):
        bdir = _good_bundle(tmp_path)
        assert (
            runner.invoke(app, ["eval", str(bdir), "--top-k", "0"], env=WIDE).exit_code
            == 2
        )
        assert (
            runner.invoke(
                app, ["eval", str(bdir), "--fail-under", "101"], env=WIDE
            ).exit_code
            == 2
        )
        assert (
            runner.invoke(
                app, ["eval", str(bdir), "--metric-threshold", "2"], env=WIDE
            ).exit_code
            == 2
        )

    def test_json_shape(self, tmp_path):
        bdir = _good_bundle(tmp_path)
        result = runner.invoke(
            app, ["eval", str(bdir), "--no-llm", "--format", "json"], env=WIDE
        )
        assert result.exit_code == 0, result.output
        payload = json.loads(result.output)
        for key in (
            "status", "bundle", "judge_mode", "top_k", "metric_thresholds",
            "fail_under", "overall_score", "question_count", "passed_count",
            "metric_means", "questions",
        ):
            assert key in payload, key
        assert payload["judge_mode"] == "heuristic"
        assert payload["status"] == "pass"
        question = payload["questions"][0]
        assert question["id"] == "refund-window"
        assert set(question["scores"]) == set(E.METRICS)
        for score in question["scores"].values():
            assert set(score) == {"value", "method", "detail"}
            assert score["method"] == "heuristic"
            assert 0.0 <= score["value"] <= 1.0
        assert question["diagnosis"] is None

    def test_json_error_on_bad_bundle(self, tmp_path):
        result = runner.invoke(
            app,
            ["eval", str(tmp_path / "missing"), "--no-llm", "--format", "json"],
            env=WIDE,
        )
        assert result.exit_code == 1
        payload = json.loads(result.output)
        assert payload["code"] == "bundle-not-found"

    def test_init_sample_writes_and_refuses_overwrite(self, tmp_path):
        bdir = _write_bundle(
            tmp_path / "kb",
            {
                "policies/refunds": (
                    {"type": "Policy", "title": "Refund policy"},
                    "Refunds within 30 days.\n",
                )
            },
        )
        first = runner.invoke(app, ["eval", str(bdir), "--init-sample"], env=WIDE)
        assert first.exit_code == 0, first.output
        written = bdir / "eval" / "golden.json"
        assert written.is_file()
        records = json.loads(written.read_text(encoding="utf-8"))
        assert records[0]["must_cite"] == ["policies/refunds"]
        second = runner.invoke(app, ["eval", str(bdir), "--init-sample"], env=WIDE)
        assert second.exit_code == 1
        assert "error [golden-exists]" in second.output

    def test_init_sample_no_concepts(self, tmp_path):
        bdir = tmp_path / "kb"
        bdir.mkdir()
        (bdir / "index.md").write_text("# index\n", encoding="utf-8")
        result = runner.invoke(app, ["eval", str(bdir), "--init-sample"], env=WIDE)
        assert result.exit_code == 1
        assert "error [golden-no-concepts]" in result.output

    def test_init_sample_set_passes_own_gate(self, tmp_path):
        # --init-sample questions must pass eval --no-llm on a healthy
        # bundle: the question wording is self-consistent by construction.
        bdir = _write_bundle(
            tmp_path / "kb",
            {
                "policies/refunds": (
                    {
                        "type": "Policy",
                        "title": "Refund policy",
                        "description": "Customers get a full refund within 30 days.",
                    },
                    "The refund policy states that customers get a full "
                    "refund within 30 days of purchase.\n",
                ),
                "policies/shipping": (
                    {
                        "type": "Policy",
                        "title": "Shipping policy",
                        "description": "Orders ship within 2 business days.",
                    },
                    "Orders ship within 2 business days via tracked "
                    "courier.\n",
                ),
            },
        )
        wrote = runner.invoke(
            app, ["eval", str(bdir), "--init-sample"], env=WIDE
        )
        assert wrote.exit_code == 0, wrote.output
        report = E.run_eval(Bundle.load(bdir), bdir, no_llm=True)
        assert all(q.passed for q in report.questions), [
            (q.id, q.failing_metrics, q.diagnosis) for q in report.questions
        ]


# ---------------------------------------------------------------------------
# Sample golden sets are self-consistent
# ---------------------------------------------------------------------------


class TestSampleGoldenSet:
    def test_sample_question_tokens_covered_by_answer(self, tmp_path):
        # Every sample question's content tokens appear in its concept's
        # own extractive answer, so the keyless answer-relevancy heuristic
        # scores 1.0 by construction — even for titles with no vocabulary
        # overlap (falls back to the cited concept id).
        bdir = _write_bundle(
            tmp_path / "kb",
            {
                "guides/getting-started": (
                    {"type": "Guide", "title": "A Completely Unrelated Heading"},
                    "This body says nothing about the heading at all.\n",
                ),
            },
        )
        concepts = list(Bundle.load(bdir).iter_concepts())
        records = E.sample_golden_set(concepts)
        assert len(records) == 1
        answer, _ = E.extractive_answer(concepts)
        value, _ = E.heuristic_answer_relevancy(records[0]["question"], answer)
        assert value == 1.0, records[0]["question"]
        assert records[0]["must_cite"] == ["guides/getting-started"]


# ---------------------------------------------------------------------------
# Temporal interplay: supersession hiding respected in retrieval
# ---------------------------------------------------------------------------


class TestTemporalInterplay:
    def _temporal_bundle(self, tmp_path: Path) -> Path:
        return _write_bundle(
            tmp_path / "kb",
            {
                "policy": (
                    {
                        "type": "Policy",
                        "title": "Old refund policy",
                        "description": "The old policy: quokka refunds in 7 days.",
                    },
                    "The old refund policy: quokka refunds processed within "
                    "7 days.\n",
                ),
                "policy-v2": (
                    {
                        "type": "Policy",
                        "title": "New refund policy",
                        "description": "The new policy: refunds in 30 days.",
                        "supersedes": ["policy"],
                    },
                    "The new refund policy: refunds processed within 30 days "
                    "of purchase.\n",
                ),
            },
        )

    def _golden(self, bdir: Path) -> None:
        _write_golden(
            bdir,
            [
                {
                    "id": "old-policy",
                    "question": "How fast were quokka refunds under the old policy?",
                    "expected_answer": "Quokka refunds in 7 days.",
                    "must_cite": ["policy"],
                }
            ],
        )

    def test_superseded_hidden_by_default(self, tmp_path):
        bdir = self._temporal_bundle(tmp_path)
        self._golden(bdir)
        report = E.run_eval(Bundle.load(bdir), bdir, no_llm=True)
        question = report.questions[0]
        assert "policy" not in question.retrieved_ids  # hidden, not deleted
        assert question.diagnosis == "retrieval"

    def test_include_superseded_retrieves(self, tmp_path):
        bdir = self._temporal_bundle(tmp_path)
        self._golden(bdir)
        report = E.run_eval(
            Bundle.load(bdir), bdir, no_llm=True, include_superseded=True
        )
        question = report.questions[0]
        assert "policy" in question.retrieved_ids
        assert question.diagnosis is None
        assert question.passed

    def test_cli_include_superseded_flag(self, tmp_path):
        bdir = self._temporal_bundle(tmp_path)
        self._golden(bdir)
        hidden = runner.invoke(
            app, ["eval", str(bdir), "--no-llm", "--format", "json"], env=WIDE
        )
        shown = runner.invoke(
            app,
            ["eval", str(bdir), "--no-llm", "--format", "json",
             "--include-superseded"],
            env=WIDE,
        )
        assert hidden.exit_code == 0 and shown.exit_code == 0
        hidden_q = json.loads(hidden.output)["questions"][0]
        shown_q = json.loads(shown.output)["questions"][0]
        assert "policy" not in hidden_q["retrieved"]
        assert "policy" in shown_q["retrieved"]
        assert shown_q["diagnosis"] is None
