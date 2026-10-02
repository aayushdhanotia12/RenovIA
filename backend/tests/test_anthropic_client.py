"""Claude client: request shape for Sonnet 5.5 and answer parsing, with a fake HTTP transport (offline)."""

import json
import unittest

try:
    import httpx2 as httpx  # the maintained successor; same API
except ImportError:  # pragma: no cover
    import httpx
import numpy as np

from backend.app.ai.anthropic_client import AnthropicClient, strict_schema
from backend.app.ai.base import ModelError
from backend.app.ai.suggester import DESCRIBE_SCHEMA, ClaudeDescriber, ClaudeSuggester, suggestion_schema
from backend.app.catalogue import get_catalogue

CAT = get_catalogue()


def answer(obj: object, stop_reason: str = "end_turn", thinking_first: bool = True) -> dict:
    content = [{"type": "thinking", "thinking": "", "signature": "sig"}] if thinking_first else []
    content.append({"type": "text", "text": json.dumps(obj, ensure_ascii=False)})
    return {"type": "message", "role": "assistant", "content": content, "stop_reason": stop_reason}


class FakeApi:
    """Replies from a list of (status, json body) and records every request body."""

    def __init__(self, *replies: tuple[int, dict]) -> None:
        self.replies, self.bodies = list(replies), []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.bodies.append(json.loads(request.content))
        status, body = self.replies.pop(0)
        return httpx.Response(status, json=body)

    def client(self, model: str = "claude-sonnet-5-5", effort: str | None = "low") -> AnthropicClient:
        return AnthropicClient("test-key", model, effort=effort, backoff_s=0, transport=httpx.MockTransport(self))


def walk(schema: object):
    if isinstance(schema, dict):
        yield schema
        for value in schema.values():
            yield from walk(value)
    elif isinstance(schema, list):
        for value in schema:
            yield from walk(value)


GOOD = {"title": "Blanco luminoso", "countertop_finish_id": "diseno-white-carrara", "profile_id": "original_q",
        "backsplash_finish_id": "none", "reason": "Ilumina la cocina."}


class RequestShapeTests(unittest.TestCase):
    def test_sonnet_5_5_request_uses_structured_outputs_and_no_forced_tool_or_temperature(self):
        api = FakeApi((200, answer({"designs": [GOOD]})))
        ClaudeSuggester(api.client(), CAT).suggest({}, "blanco", None, "es")
        body = api.bodies[0]
        self.assertEqual(body["model"], "claude-sonnet-5-5")
        self.assertEqual(body["output_config"]["format"]["type"], "json_schema")
        self.assertEqual(body["output_config"]["effort"], "low")
        for key in ("tools", "tool_choice", "temperature", "top_p", "top_k", "thinking"):
            self.assertNotIn(key, body)

    def test_haiku_4_5_gets_no_effort_parameter(self):
        api = FakeApi((200, answer({"designs": [GOOD]})))
        ClaudeSuggester(api.client("claude-haiku-4-5-20251001"), CAT).suggest({}, "", None, "en")
        self.assertNotIn("effort", api.bodies[0]["output_config"])

    def test_sent_schema_has_no_length_or_count_limits_and_every_object_is_closed(self):
        sent = strict_schema(suggestion_schema(CAT))
        for node in walk(sent):
            for key in ("minItems", "maxItems", "minLength", "maxLength", "oneOf", "allOf"):
                self.assertNotIn(key, node)
            if node.get("type") == "object":
                self.assertIs(node["additionalProperties"], False)
        self.assertEqual(sent["properties"]["designs"]["description"], "Exactly 3 items.")
        self.assertIn("At most 48 characters", sent["properties"]["designs"]["items"]["properties"]["title"]["description"])

    def test_every_describe_field_is_required_so_the_optional_parameter_limit_is_not_hit(self):
        self.assertEqual(set(DESCRIBE_SCHEMA["required"]), set(DESCRIBE_SCHEMA["properties"]))
        item = suggestion_schema(CAT)["properties"]["designs"]["items"]
        self.assertEqual(set(item["required"]), set(item["properties"]))

    def test_the_original_schema_is_not_modified_when_sent(self):
        schema = suggestion_schema(CAT)
        before = json.dumps(schema, sort_keys=True)
        strict_schema(schema)
        self.assertEqual(json.dumps(schema, sort_keys=True), before)


class AnswerTests(unittest.TestCase):
    def test_json_after_a_thinking_block_gives_three_validated_suggestions(self):
        designs = [GOOD, dict(GOOD, countertop_finish_id="estilo-caracatta", profile_id="essence"),
                   dict(GOOD, countertop_finish_id="basik-almond-leather", profile_id="basik"),
                   dict(GOOD, title="cuarta")]
        api = FakeApi((200, answer({"designs": designs})))
        out = ClaudeSuggester(api.client(), CAT).suggest({}, "", None, "es")
        self.assertEqual([d["countertop_finish_id"] for d in out],
                         ["diseno-white-carrara", "estilo-caracatta", "basik-almond-leather"])

    def test_describer_returns_the_eight_fields(self):
        desc = {k: "not visible" for k in DESCRIBE_SCHEMA["properties"]}
        desc["colours"] = ["white", "oak"]
        api = FakeApi((200, answer(desc)))
        out = ClaudeDescriber(api.client()).describe(np.zeros((40, 60, 3), np.uint8))
        self.assertEqual(out["colours"], ["white", "oak"])
        self.assertEqual(api.bodies[0]["messages"][0]["content"][0]["type"], "image")

    def test_an_answer_cut_off_at_max_tokens_is_an_error_not_a_guess(self):
        api = FakeApi((200, {"content": [{"type": "text", "text": '{"designs": [{"ti'}], "stop_reason": "max_tokens"}))
        with self.assertRaises(ModelError):
            api.client().json_call("s", [{"type": "text", "text": "x"}], DESCRIBE_SCHEMA)

    def test_a_400_is_raised_at_once_without_retrying(self):
        api = FakeApi((400, {"type": "error", "error": {"type": "invalid_request_error", "message": "bad"}}))
        with self.assertRaises(ModelError):
            api.client().json_call("s", [{"type": "text", "text": "x"}], DESCRIBE_SCHEMA)
        self.assertEqual(len(api.bodies), 1)

    def test_an_overloaded_529_is_retried_and_the_second_answer_is_used(self):
        api = FakeApi((529, {"type": "error"}), (200, answer({"ok": True}, thinking_first=False)))
        out = api.client().json_call("s", [{"type": "text", "text": "x"}], {"type": "object", "properties": {}})
        self.assertEqual((out, len(api.bodies)), ({"ok": True}, 2))


if __name__ == "__main__":
    unittest.main()
