"""Provider adapters. The rest of the pipeline only sees generate() and ProviderError."""
import time
from dataclasses import dataclass


@dataclass
class ProviderResponse:
    text: str
    model: str
    latency_ms: int
    tokens_in: int = 0
    tokens_out: int = 0


class ProviderError(Exception):
    """kind: timeout | rate_limit | unavailable | quota | auth | bad_request | not_found | other"""

    RETRYABLE = {"timeout", "rate_limit", "unavailable", "other"}

    def __init__(self, kind, message, status=None):
        super().__init__(message)
        self.kind, self.status = kind, status

    @property
    def retryable(self):
        return self.kind in self.RETRYABLE


def classify(exc):
    """Map SDK / network exceptions to ProviderError kinds."""
    status = getattr(exc, "code", None) or getattr(exc, "status_code", None)
    text = str(exc)
    name = type(exc).__name__
    if "Timeout" in name or "timed out" in text.lower() or "WinError 10060" in text:
        return ProviderError("timeout", text[:300])
    if status == 429:
        kind = "quota" if "quota" in text.lower() and "exceeded" in text.lower() and "per day" in text.lower() else "rate_limit"
        return ProviderError(kind, text[:300], status)
    if status in (500, 502, 503, 504):
        return ProviderError("unavailable", text[:300], status)
    if status in (401, 403):
        return ProviderError("auth", text[:300], status)
    if status == 404:
        return ProviderError("not_found", text[:300], status)
    if status == 400:
        return ProviderError("bad_request", text[:300], status)
    return ProviderError("other", f"{name}: {text[:280]}", status)


class GeminiProvider:
    name = "gemini"

    def __init__(self, api_key, temperature=0.2, thinking_level=None, max_output_tokens=16384, timeout_seconds=90):
        from google import genai
        from google.genai import types
        self._types = types
        self._client = genai.Client(api_key=api_key,
                                    http_options=types.HttpOptions(timeout=int(timeout_seconds * 1000)))
        self.temperature, self.thinking_level, self.max_output_tokens = temperature, thinking_level, max_output_tokens

    def generate(self, model, system, user, schema):
        types = self._types
        config = dict(system_instruction=system, response_mime_type="application/json", response_schema=schema,
                      temperature=self.temperature, max_output_tokens=self.max_output_tokens,
                      automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True))
        if self.thinking_level:
            config["thinking_config"] = types.ThinkingConfig(thinking_level=self.thinking_level)
        start = time.perf_counter()
        try:
            response = self._client.models.generate_content(model=model, contents=user,
                                                            config=types.GenerateContentConfig(**config))
        except Exception as exc:        # the SDK raises several exception families; classify them all
            raise classify(exc) from exc
        usage = response.usage_metadata
        return ProviderResponse(text=response.text or "", model=model,
                                latency_ms=int((time.perf_counter() - start) * 1000),
                                tokens_in=getattr(usage, "prompt_token_count", 0) or 0,
                                tokens_out=getattr(usage, "candidates_token_count", 0) or 0)


def build_provider(app_config):
    from config.loader import load_config
    cfg = load_config("genai")
    key = app_config.get("GEMINI_API_KEY")
    if not key:
        raise ProviderError("auth", "GEMINI_API_KEY is not set")
    g = cfg["generation"]
    return GeminiProvider(key, temperature=g["temperature"], thinking_level=g.get("thinking_level"),
                          max_output_tokens=g["max_output_tokens"], timeout_seconds=g["timeout_seconds"])


def model_names(app_config, phase="outline"):
    """[main, fallback] for a phase. GEMINI_MODEL overrides the Phase-1 model."""
    from config.loader import load_config
    cfg = load_config("genai")
    main = (app_config.get("GEMINI_MODEL") or cfg["model"]) if phase == "outline" else cfg.get("module_model", cfg["model"])
    fallback = cfg.get("fallback_model")
    return [main, fallback if fallback != main else None]
