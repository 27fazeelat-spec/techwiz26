"""Structured generation with controlled retry, JSON repair and model fallback (SRS Step 39).

  - retryable errors (timeout, 5xx): exponential backoff with jitter, max_attempts per model
  - rate limit (429) or "high demand" (503) with a fallback left: switch to the fallback at once, and skip the busy
    model for busy_cooldown_seconds, so parallel calls and the next plans do not wait for the same refusal
  - invalid JSON / schema mismatch: one repair attempt that sends the validation errors back
  - main model still unavailable: the fallback model gets the same number of attempts
  - non-retryable errors (auth, bad request, model not found): fail fast
Every attempt is recorded, so failures and retries are evidence, not guesswork.
"""
import json
import random
import threading
import time
from dataclasses import dataclass, field

from pydantic import ValidationError

from config.loader import load_config
from genai_pipeline.providers import ProviderError


@dataclass
class CallResult:
    ok: bool
    parsed: object = None
    raw: str = ""
    model: str = ""
    attempts: list = field(default_factory=list)
    schema_errors: list = field(default_factory=list)
    latency_ms: int = 0
    tokens_in: int = 0
    tokens_out: int = 0
    error: str = ""


_busy_until = {}                     # model -> time.monotonic() until which it is skipped while a fallback exists
_busy_lock = threading.Lock()


def _is_busy(model):
    with _busy_lock:
        return _busy_until.get(model, 0) > time.monotonic()


def _mark_busy(model, seconds):
    with _busy_lock:
        _busy_until[model] = time.monotonic() + seconds


def reset_busy():
    """Forget busy models (tests)."""
    with _busy_lock:
        _busy_until.clear()


def _schema_errors(exc):
    if isinstance(exc, ValidationError):
        return [{"loc": ".".join(str(p) for p in e["loc"]), "msg": e["msg"]} for e in exc.errors()[:20]]
    return [{"loc": "", "msg": str(exc)[:300]}]


def call_structured(provider, models, system, user, schema, sleep=time.sleep):
    """Return a CallResult. models: [main, fallback] (fallback may be None)."""
    cfg = load_config("genai")["retry"]
    result = CallResult(ok=False)
    started = time.perf_counter()
    repaired = False
    chain = [m for m in models if m]
    for position, model in enumerate(chain):
        has_fallback = position < len(chain) - 1
        if has_fallback and _is_busy(model):
            result.attempts.append({"model": model, "attempt": 0, "repair": False, "outcome": "skipped",
                                    "message": "refused as busy or rate-limited moments ago; went to the fallback"})
            continue
        for attempt in range(1, cfg["max_attempts"] + 1):
            prompt = user
            if result.schema_errors and cfg.get("repair_invalid_json") and not repaired:
                prompt = (f"{user}\n\nYour previous answer did not match the required JSON schema. Errors:\n"
                          f"{json.dumps(result.schema_errors, indent=1)}\nReturn corrected JSON only.")
                repaired = True
            record = {"model": model, "attempt": attempt, "repair": prompt is not user}
            try:
                response = provider.generate(model, system, prompt, schema)
            except ProviderError as exc:
                record.update(outcome="error", error_type=exc.kind, message=str(exc)[:200])
                result.attempts.append(record)
                result.error = f"{exc.kind}: {exc}"
                if exc.kind in ("rate_limit", "quota") or (exc.kind == "unavailable" and has_fallback):
                    if has_fallback:                   # busy or out of quota: retrying the same model only waits
                        _mark_busy(model, cfg.get("busy_cooldown_seconds", 120))
                    break
                if not exc.retryable:
                    if exc.kind == "not_found":
                        break                          # try the fallback model
                    result.latency_ms = int((time.perf_counter() - started) * 1000)
                    return result
                if attempt < cfg["max_attempts"]:
                    sleep(cfg["base_delay_seconds"] * (2 ** (attempt - 1)) + random.uniform(0, 0.5))
                continue
            result.raw, result.model = response.text, response.model
            result.tokens_in += response.tokens_in
            result.tokens_out += response.tokens_out
            record["latency_ms"] = response.latency_ms
            try:
                result.parsed = schema.model_validate_json(response.text)
            except (ValidationError, ValueError) as exc:
                result.schema_errors = _schema_errors(exc)
                record.update(outcome="invalid_json", error_type="schema", message=result.schema_errors[0]["msg"][:200])
                result.attempts.append(record)
                result.error = "invalid_json: response did not match the schema"
                if repaired or not cfg.get("repair_invalid_json"):
                    result.latency_ms = int((time.perf_counter() - started) * 1000)
                    return result
                continue
            record["outcome"] = "ok"
            result.attempts.append(record)
            result.ok, result.error = True, ""
            result.latency_ms = int((time.perf_counter() - started) * 1000)
            return result
    result.latency_ms = int((time.perf_counter() - started) * 1000)
    return result
