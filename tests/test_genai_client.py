"""Retry, repair and fallback behaviour (SRS Step 39)."""
import json
import time

import pytest
from pydantic import BaseModel

from genai_pipeline.client import call_structured, reset_busy
from genai_pipeline.prompts import load
from genai_pipeline.providers import ProviderResponse, classify, model_names
from schemas.plan import OutlineRequirement
from tests.fakes import SequenceProvider, rate_limited, unauthorised, unavailable


class Small(BaseModel):
    answer: str


GOOD = json.dumps({"answer": "ok"})
MODELS = ["main-model", "fallback-model"]


@pytest.fixture(autouse=True)
def fresh_busy_list():
    reset_busy()
    yield
    reset_busy()


def call(outcomes, models=MODELS):
    provider = SequenceProvider(outcomes)
    return call_structured(provider, models, "system", "user", Small, sleep=lambda s: None, hedge_after=0), provider


def test_success_first_time():
    result, _ = call([GOOD])
    assert result.ok and result.parsed.answer == "ok" and len(result.attempts) == 1


def test_503_on_the_only_model_is_retried_then_succeeds():
    result, provider = call([unavailable(), GOOD], models=["main-model", None])
    assert result.ok and provider.models == ["main-model", "main-model"]
    assert [a["outcome"] for a in result.attempts] == ["error", "ok"]


def test_a_busy_main_model_goes_to_the_fallback_and_is_tried_last_for_a_while():
    result, provider = call([unavailable(), GOOD])
    assert result.ok and provider.models == ["main-model", "fallback-model"]
    again, provider = call([GOOD])                       # the next call does not wait for the same refusal
    assert again.ok and provider.models == ["fallback-model"]
    reset_busy()
    third, provider = call([GOOD])
    assert provider.models == ["main-model"]


def test_a_busy_model_is_still_the_last_resort_when_the_fallback_fails():
    call([unavailable(), GOOD])                          # main is now busy
    result, provider = call([unavailable(), GOOD])      # the fallback is busy too: back to the main model
    assert result.ok and provider.models == ["fallback-model", "main-model"]


class SlowFirstProvider:
    """The first request hangs; any later one answers at once."""

    def __init__(self):
        self.models, self.lock = [], __import__("threading").Lock()

    def generate(self, model, system, user, schema):
        with self.lock:
            self.models.append(model)
            first = len(self.models) == 1
        if first:
            time.sleep(2)
        return ProviderResponse(text=GOOD, model=model, latency_ms=1)


def test_a_stuck_call_is_sent_to_the_other_model_and_the_first_answer_wins():
    provider = SlowFirstProvider()
    started = time.perf_counter()
    result = call_structured(provider, MODELS, "system", "user", Small, sleep=lambda s: None, hedge_after=0.1)
    assert result.ok and result.model == "fallback-model"
    assert provider.models == ["main-model", "fallback-model"] and result.attempts[0]["hedged_to"] == "fallback-model"
    assert time.perf_counter() - started < 1.5           # did not wait for the stuck request


def test_every_phase_has_a_second_model():
    for phase in ("outline", "module"):
        main, fallback = model_names({}, phase)
        assert main and fallback and main != fallback


def test_stage_labels_are_read_as_stage_codes():
    base = {"requirement_id": "R-X-01-001", "mandatory": True, "priority": "High", "category": "Safety",
            "source_document_id": "X-01", "source_section_id": "1"}
    for label, code in (("Day 1", "D1"), ("week 1", "W1"), ("First 30 Days", "D30"), ("30 days", "D30"), ("D60", "D60")):
        assert OutlineRequirement(**base, due_stage=label).due_stage == code
    with pytest.raises(Exception):
        OutlineRequirement(**base, due_stage="Someday")


def test_rate_limit_goes_straight_to_fallback():
    result, provider = call([rate_limited(), GOOD])
    assert result.ok and provider.models == ["main-model", "fallback-model"]


def test_invalid_json_gets_one_repair_attempt():
    result, _ = call(["not json at all", GOOD])
    assert result.ok and result.attempts[0]["outcome"] == "invalid_json" and result.attempts[1]["repair"]


def test_second_invalid_json_fails_without_looping():
    result, provider = call(["{}", "{\"wrong\": 1}", GOOD])
    assert not result.ok and len(provider.models) == 2 and result.schema_errors


def test_auth_error_fails_fast():
    result, provider = call([unauthorised(), GOOD])
    assert not result.ok and len(provider.models) == 1 and "auth" in result.error


def test_retries_are_bounded():
    result, provider = call([unavailable()] * 10)
    assert not result.ok and len(provider.models) == 3          # main once (busy), then 2 on the fallback


def test_error_classification():
    class Fake(Exception):
        def __init__(self, code, msg=""):
            super().__init__(msg)
            self.code = code
    assert classify(Fake(503)).kind == "unavailable"
    assert classify(Fake(429, "rate")).kind == "rate_limit"
    assert classify(Fake(401)).kind == "auth"
    assert classify(TimeoutError("timed out")).kind == "timeout"


def test_prompt_templates_are_versioned():
    for name in ("plan_outline", "module_content"):
        t = load(name)
        assert t.version and len(t.sha256) == 64 and "DATA" in t.system
