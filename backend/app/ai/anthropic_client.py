"""Minimal Claude Messages API client (httpx) that asks for JSON matching a schema.

It uses structured outputs (`output_config.format` with type `json_schema`), which
every current Claude model supports. It does not force a tool call: Claude Sonnet 5.5
(released 28 Sep 2026) rejects `tool_choice` of type "tool" or "any" with a 400, and
also rejects a non-default `temperature`, `top_p` or `top_k`, so none are sent.

Structured outputs accept only part of JSON Schema. `strict_schema` removes the
keywords the API refuses (minItems, maxLength, ...) and writes them into the field's
description instead; our own validation still enforces them on the answer.

The answer's JSON arrives in a `text` block, possibly after `thinking` blocks
(adaptive thinking is on by default on Sonnet 5.5), so blocks are read by type.
Images are downscaled to at most 1568 px on the long side before sending.
"""

from __future__ import annotations

import base64
import json
import time

import cv2
try:
    import httpx2 as httpx  # the maintained successor; same API
except ImportError:  # pragma: no cover
    import httpx
import numpy as np

from .base import ModelError

API_VERSION = "2023-06-01"
RETRYABLE = (408, 429, 500, 502, 503, 504, 529)

# JSON Schema keywords that structured outputs refuse, and how to say them in words.
_AS_WORDS = {
    "minItems": "at least {} items", "maxItems": "at most {} items",
    "minLength": "at least {} characters", "maxLength": "at most {} characters",
    "minimum": "at least {}", "maximum": "at most {}",
    "exclusiveMinimum": "more than {}", "exclusiveMaximum": "less than {}",
    "multipleOf": "a multiple of {}", "uniqueItems": "no repeated items",
}
_DROPPED = {"not", "patternProperties", "prefixItems", "dependencies", "dependentSchemas", "dependentRequired"}


def strict_schema(schema: dict) -> dict:
    """Copy of `schema` that structured outputs accept: unsupported limits move into
    the description, `oneOf` becomes `anyOf`, and every object is closed."""
    if not isinstance(schema, dict):
        return schema
    if "allOf" in schema:
        raise ValueError("structured outputs do not support allOf; flatten the schema")
    out: dict = {}
    words: list[str] = []
    if schema.get("minItems") is not None and schema.get("minItems") == schema.get("maxItems"):
        words.append(f"exactly {schema['minItems']} items")
    for key, value in schema.items():
        if key in _AS_WORDS:
            if key in ("minItems", "maxItems") and words and words[0].startswith("exactly"):
                continue
            if key == "uniqueItems" and not value:
                continue
            words.append(_AS_WORDS[key].format(value))
        elif key in _DROPPED:
            continue
        elif key in ("properties", "$defs", "definitions"):
            out[key] = {name: strict_schema(sub) for name, sub in value.items()}
        elif key == "items":
            out[key] = strict_schema(value)
        elif key in ("anyOf", "oneOf"):
            out["anyOf"] = [strict_schema(sub) for sub in value]
        else:
            out[key] = value
    if words:
        note = "; ".join(words).capitalize() + "."
        out["description"] = f"{out['description']} ({note})" if out.get("description") else note
    if out.get("type") == "object" or "properties" in out:
        out["additionalProperties"] = False
    return out


def supports_effort(model: str) -> bool:
    """The effort parameter exists on Opus 4.5+, Sonnet 4.6+, Fable and Mythos; Haiku 4.5
    and Sonnet 4.5 return a 400 if it is sent."""
    return not (model.startswith("claude-haiku") or model.startswith("claude-sonnet-4-5")
                or model.startswith("claude-3"))


def parse_json_answer(data: dict) -> dict:
    stop = data.get("stop_reason")
    if stop == "max_tokens":
        raise ModelError("Claude's answer was cut off at max_tokens; raise max_tokens or lower the effort")
    if stop == "refusal":
        raise ModelError("Claude declined to answer this request")
    texts = [b.get("text") or "" for b in data.get("content") or [] if b.get("type") == "text"]
    for candidate in ["".join(texts)] + texts[::-1]:
        try:
            out = json.loads(candidate)
        except (json.JSONDecodeError, TypeError):
            continue
        if isinstance(out, dict):
            return out
    raise ModelError("Claude's answer did not contain a JSON object")


def image_block(image_bgr: np.ndarray, max_side: int = 1568) -> dict:
    h, w = image_bgr.shape[:2]
    scale = min(1.0, max_side / max(h, w))
    if scale < 1.0:
        image_bgr = cv2.resize(image_bgr, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_AREA)
    ok, buf = cv2.imencode(".jpg", image_bgr, [cv2.IMWRITE_JPEG_QUALITY, 88])
    if not ok:
        raise ModelError("could not encode image")
    return {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg",
                                         "data": base64.b64encode(buf.tobytes()).decode()}}


class AnthropicClient:
    def __init__(self, api_key: str, model: str, base_url: str = "https://api.anthropic.com",
                 effort: str | None = "low", timeout_s: float = 90.0, retries: int = 2,
                 backoff_s: float = 1.5, transport: httpx.BaseTransport | None = None) -> None:
        if not api_key:
            raise ModelError("ANTHROPIC_API_KEY is not set")
        self.api_key, self.model, self.base_url = api_key, model, base_url.rstrip("/")
        self.effort = effort or None
        self.timeout_s, self.retries, self.backoff_s, self.transport = timeout_s, retries, backoff_s, transport

    def request_body(self, system: str, content: list[dict], schema: dict, max_tokens: int) -> dict:
        output_config: dict = {"format": {"type": "json_schema", "schema": strict_schema(schema)}}
        if self.effort and supports_effort(self.model):
            output_config["effort"] = self.effort
        return {"model": self.model, "max_tokens": max_tokens, "system": system,
                "messages": [{"role": "user", "content": content}], "output_config": output_config}

    def json_call(self, system: str, content: list[dict], schema: dict, max_tokens: int = 4000) -> dict:
        """One request whose answer is a JSON object shaped by `schema`.

        Busy or unreachable API: retried with backoff. Any other 4xx: raised at once,
        because the same request would fail again."""
        body = self.request_body(system, content, schema, max_tokens)
        headers = {"x-api-key": self.api_key, "anthropic-version": API_VERSION, "content-type": "application/json"}
        last_error = ModelError("Claude API not called")
        for attempt in range(self.retries + 1):
            try:
                with httpx.Client(timeout=self.timeout_s, transport=self.transport) as http:
                    r = http.post(f"{self.base_url}/v1/messages", json=body, headers=headers)
            except httpx.HTTPError as e:
                last_error = ModelError(f"Claude API unreachable: {e}")
            else:
                if r.status_code in RETRYABLE:
                    last_error = ModelError(f"Claude API busy ({r.status_code})")
                elif r.status_code >= 400:
                    raise ModelError(f"Claude API error {r.status_code}: {r.text[:300]}")
                else:
                    return parse_json_answer(r.json())
            if attempt < self.retries:
                time.sleep(self.backoff_s * (attempt + 1))
        raise last_error
