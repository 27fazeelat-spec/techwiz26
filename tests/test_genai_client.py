"""Retry, repair and fallback behaviour (SRS Step 39)."""
import json

from pydantic import BaseModel

from genai_pipeline.client import call_structured
from genai_pipeline.prompts import load
from genai_pipeline.providers import classify
from tests.fakes import SequenceProvider, rate_limited, unauthorised, unavailable


class Small(BaseModel):
    answer: str


GOOD = json.dumps({"answer": "ok"})
MODELS = ["main-model", "fallback-model"]


def call(outcomes):
    provider = SequenceProvider(outcomes)
    return call_structured(provider, MODELS, "system", "user", Small, sleep=lambda s: None), provider


def test_success_first_time():
    result, _ = call([GOOD])
    assert result.ok and result.parsed.answer == "ok" and len(result.attempts) == 1


def test_503_is_retried_then_succeeds():
    result, provider = call([unavailable(), GOOD])
    assert result.ok and provider.models == ["main-model", "main-model"]
    assert [a["outcome"] for a in result.attempts] == ["error", "ok"]


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
    assert not result.ok and len(provider.models) == 4          # 2 per model, main + fallback


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
