"""Retry, repair and fallback behaviour (SRS Step 39)."""
import json

from pydantic import BaseModel

import pytest

from genai_pipeline.client import call_structured, reset_busy
from genai_pipeline.prompts import load
from genai_pipeline.providers import classify
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
    return call_structured(provider, models, "system", "user", Small, sleep=lambda s: None), provider


def test_success_first_time():
    result, _ = call([GOOD])
    assert result.ok and result.parsed.answer == "ok" and len(result.attempts) == 1


def test_503_on_the_only_model_is_retried_then_succeeds():
    result, provider = call([unavailable(), GOOD], models=["main-model", None])
    assert result.ok and provider.models == ["main-model", "main-model"]
    assert [a["outcome"] for a in result.attempts] == ["error", "ok"]


def test_a_busy_main_model_goes_to_the_fallback_and_is_skipped_for_a_while():
    result, provider = call([unavailable(), GOOD])
    assert result.ok and provider.models == ["main-model", "fallback-model"]
    again, provider = call([GOOD])                       # the next call does not wait for the same refusal
    assert again.ok and provider.models == ["fallback-model"]
    assert [a["outcome"] for a in again.attempts] == ["skipped", "ok"]
    reset_busy()
    third, provider = call([GOOD])
    assert provider.models == ["main-model"]


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
