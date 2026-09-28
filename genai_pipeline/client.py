"""Structured generation with controlled retry, JSON repair and model fallback (SRS Step 39).

  - retryable errors (timeout, 5xx): exponential backoff with jitter, max_attempts per model
  - rate limit (429) or "high demand" (503) with a fallback left: switch to the fallback at once, and try the busy
    model last for busy_cooldown_seconds, so parallel calls and the next plans do not wait for the same refusal
  - a call with no answer after hedge_after_seconds is sent again to the other model; the first good answer wins,
    so one stuck request does not hold a plan for the full timeout
  - every model busy: wait busy_round_delay_seconds and go through the models again (busy_rounds in all)
  - invalid JSON / schema mismatch: one repair attempt that sends the validation errors back
  - main model still unavailable: the fallback model gets the same number of attempts
  - non-retryable errors (auth, bad request, model not found): fail fast
Every attempt is recorded, so failures and retries are evidence, not guesswork.
"""
import json
import random
import threading
import time
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from concurrent.futures import TimeoutError as FutureTimeout
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


def _generate(provider, model, other, system, prompt, schema, hedge_after, record):
    """provider.generate, sent again to `other` if no answer arrives within hedge_after seconds."""
    if not hedge_after:
        return provider.generate(model, system, prompt, schema)
    pool = ThreadPoolExecutor(max_workers=2)
    try:
        first = pool.submit(provider.generate, model, system, prompt, schema)
        try:
            return first.result(timeout=hedge_after)
        except FutureTimeout:
            pass
        record["hedged_to"] = other or model
        pending, error = {first, pool.submit(provider.generate, other or model, system, prompt, schema)}, None
        while pending:
            done, pending = wait(pending, return_when=FIRST_COMPLETED)
            for future in done:
                try:
                    return future.result()
                except ProviderError as exc:
                    error = exc
        raise error
    finally:
        pool.shutdown(wait=False)                  # a slower duplicate finishes on its own; its answer is dropped


def _schema_errors(exc):
    if isinstance(exc, ValidationError):
        return [{"loc": ".".join(str(p) for p in e["loc"]), "msg": e["msg"]} for e in exc.errors()[:20]]
    return [{"loc": "", "msg": str(exc)[:300]}]


BUSY_KINDS = ("unavailable", "rate_limit", "timeout")


def call_structured(provider, models, system, user, schema, sleep=time.sleep, hedge_after=None):
    """Return a CallResult. models: [main, fallback, ...] (None entries are ignored).
    hedge_after: seconds before a slow call is also sent to the other model (default from config; 0 = never)."""
    cfg = load_config("genai")["retry"]
    result = CallResult(ok=False)
    started = time.perf_counter()
    for round_no in range(cfg.get("busy_rounds", 1)):
        if round_no:
            sleep(cfg.get("busy_round_delay_seconds", 8) * round_no)
        _one_round(provider, models, system, user, schema, sleep, hedge_after, cfg, result)
        last = result.attempts[-1] if result.attempts else {}
        if result.ok or last.get("error_type") not in BUSY_KINDS:
            break                                  # done, or a failure that waiting will not fix
    result.latency_ms = int((time.perf_counter() - started) * 1000)
    return result


def _one_round(provider, models, system, user, schema, sleep, hedge_after, cfg, result):
    """One pass through the models, filling `result`."""
    hedge_after = cfg.get("hedge_after_seconds", 0) if hedge_after is None else hedge_after
    repaired = False
    named = [m for m in models if m]
    chain = [m for m in named if not _is_busy(m)] + [m for m in named if _is_busy(m)]   # busy models go last
    for position, model in enumerate(chain):
        has_fallback = position < len(chain) - 1
        other = next((m for m in chain if m != model), None)
        for attempt in range(1, cfg["max_attempts"] + 1):
            prompt = user
            if result.schema_errors and cfg.get("repair_invalid_json") and not repaired:
                prompt = (f"{user}\n\nYour previous answer did not match the required JSON schema. Errors:\n"
                          f"{json.dumps(result.schema_errors, indent=1)}\nReturn corrected JSON only.")
                repaired = True
            record = {"model": model, "attempt": attempt, "repair": prompt is not user}
            try:
                response = _generate(provider, model, other, system, prompt, schema, hedge_after, record)
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
                    return
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
                    return
                continue
            record["outcome"] = "ok"
            result.attempts.append(record)
            result.ok, result.error = True, ""
            return
