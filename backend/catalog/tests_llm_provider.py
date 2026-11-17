"""Mistral chat payload stays valid, and a 400 is logged without the key."""
from __future__ import annotations

import json
import math
import os
from datetime import date
from unittest.mock import patch

import httpx
from django.test import SimpleTestCase, override_settings

from assist import companion
from catalog import ingest, llm_provider

KEY = "sk-test-secret-do-not-log"
# Cap the companion is allowed to send: 6 sections × 150 dishes, each with a
# 200-character note and 20 component names. That is the snapshot behind a
# house-wide question (no section named → menu is not sliced).
_DISH = (
    "Korean chicken burger — "
    + ("£20 with skinny fries and house slaw. " * 8)[:200]
    + " | "
    + "; ".join(f"component {i:02d} thigh" for i in range(20))
)
FULL_MENU_CHARS = 6 * 150 * len(_DISH)


class _Client:
    posts: list[dict] = []
    response: httpx.Response | None = None

    def __init__(self, *args, **kwargs):
        del args, kwargs

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def post(self, url, headers=None, json=None):
        _Client.posts.append({"url": url, "headers": headers or {}, "json": json})
        return _Client.response


def _content_response(content: str) -> httpx.Response:
    return httpx.Response(
        200,
        json={"choices": [{"message": {"content": content}}]},
        request=httpx.Request(
            "POST",
            llm_provider.CHAT_URL,
            headers={"Authorization": f"Bearer {KEY}"},
        ),
    )


def _ok_response() -> httpx.Response:
    return _content_response('{"reply": "Fire the jus."}')


def _error_response(status: int, payload: dict) -> httpx.Response:
    return httpx.Response(
        status,
        json=payload,
        request=httpx.Request(
            "POST",
            llm_provider.CHAT_URL,
            headers={"Authorization": f"Bearer {KEY}"},
        ),
    )


@override_settings(
    MISTRAL_API_KEY=KEY,
    LLM_MODEL="mistral-medium-latest",
    COMPANION_MODEL="mistral-large-latest",
)
class MistralPayloadTests(SimpleTestCase):
    def setUp(self):
        _Client.posts = []
        _Client.response = _ok_response()
        self.env = patch.dict(
            os.environ,
            {
                "MISTRAL_API_KEY": KEY,
                "LLM_MODEL": "mistral-medium-latest",
                "COMPANION_MODEL": "mistral-large-latest",
            },
            clear=False,
        )
        self.env.start()
        os.environ.pop("LLM_MAX_TOKENS", None)
        self.client = patch.object(llm_provider.httpx, "Client", _Client)
        self.client.start()

    def tearDown(self):
        self.client.stop()
        self.env.stop()

    def test_full_menu_plus_32768_exceeds_a_128k_window(self):
        """The reservation the companion used to send, against a capped menu.

        Six sections at the dish cap are about 175k tokens. Plus 32768 that
        crosses a 128k window (Medium 3.1) and is the HTTP 400 Mistral
        documents for prompt + max_tokens over context. Large 4's 1M window
        still fits that sum, which is why the log of the error body matters.
        """
        prompt_tokens = FULL_MENU_CHARS // 4
        self.assertGreater(prompt_tokens + 32768, 131_072)
        self.assertLess(prompt_tokens + llm_provider.COMPANION_MAX_TOKENS, 1_048_576)
        old = {
            "model": "mistral-medium-latest",
            "temperature": 0,
            "max_tokens": 32768,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": "You receive a JSON snapshot."},
                {"role": "user", "content": "x" * (110_000 * 4)},
            ],
        }
        self.assertIn("context", llm_provider.mistral_payload_issues(old))

    def test_builder_clamps_a_prompt_that_used_to_400(self):
        llm_provider.chat_completion_json(
            system="Extract JSON only.",
            user_text="x" * (110_000 * 4),
            model="mistral-medium-latest",
        )
        body = _Client.posts[0]["json"]
        self.assertEqual(llm_provider.mistral_payload_issues(body), [])
        prompt = llm_provider.estimate_tokens(body["messages"])
        self.assertLess(prompt + body["max_tokens"], llm_provider.context_limit(body["model"]))
        self.assertLess(body["max_tokens"], 32768)
        self.assertNotIn(KEY, json.dumps(body))

    def test_history_is_normalised_before_post(self):
        llm_provider.chat_completion_json(
            system="Second system. Answer in JSON.",
            user_text="What should I fire first?",
            model="bad model id",
            temperature=9,
            max_tokens=10**9,
            messages=[
                {"role": "assistant", "content": "Morning."},
                {"role": "system", "content": "First system."},
                {"role": "user", "content": "   "},
                {"role": "user", "content": None},
                {"role": "user", "content": "Soup of the day?"},
                {"role": "user", "content": {"note": "not a string"}},
                {"role": "assistant", "content": ""},
                {"role": "assistant", "content": "Start the stock."},
                {"role": "assistant", "content": "Then the garnish."},
            ],
        )
        body = _Client.posts[0]["json"]
        self.assertEqual(llm_provider.mistral_payload_issues(body), [])
        roles = [m["role"] for m in body["messages"]]
        self.assertEqual(roles[0], "system")
        self.assertEqual(roles.count("system"), 1)
        self.assertEqual(roles[-1], "user")
        self.assertNotIn("", [m["content"] for m in body["messages"]])
        conversation = [r for r in roles if r != "system"]
        self.assertTrue(all(a != b for a, b in zip(conversation, conversation[1:])))
        self.assertEqual(body["model"], llm_provider.DEFAULT_MODEL)
        self.assertLessEqual(body["temperature"], llm_provider.TEMPERATURE_MAX)
        self.assertGreaterEqual(body["temperature"], 0)
        self.assertLessEqual(body["max_tokens"], llm_provider.completion_ceiling(body["model"]))
        self.assertEqual(body["response_format"], {"type": "json_object"})
        blob = " ".join(
            m["content"] for m in body["messages"] if isinstance(m["content"], str)
        )
        self.assertIn("json", blob.casefold())
        self.assertIn("What should I fire first?", blob)
        # Systems collapsed to one, and the blank assistant turn is gone.
        self.assertIn("First system.", body["messages"][0]["content"])
        self.assertIn("Second system.", body["messages"][0]["content"])

    def test_json_word_is_added_when_the_prompt_never_says_it(self):
        body = llm_provider.build_chat_body(
            system="You are the kitchen companion.",
            user_content="Fire table 4.",
            model="mistral-large-latest",
            max_tokens=256,
        )
        blob = " ".join(m["content"] for m in body["messages"])
        self.assertIn("json", blob.casefold())
        self.assertEqual(llm_provider.mistral_payload_issues(body), [])

    def test_companion_does_not_reserve_32768(self):
        with patch.object(companion, "_require_key", lambda: None):
            data, model = companion._call("Reply as JSON.", "Scale the jus for 20.")
        self.assertEqual(data["reply"], "Fire the jus.")
        self.assertEqual(model, "mistral-large-latest")
        body = _Client.posts[0]["json"]
        self.assertEqual(body["max_tokens"], llm_provider.COMPANION_MAX_TOKENS)
        self.assertEqual(body["model"], "mistral-large-latest")
        self.assertEqual(llm_provider.mistral_payload_issues(body), [])

    def test_ingest_default_stays_32768_when_the_prompt_is_small(self):
        llm_provider.chat_completion_json(
            system="Return JSON only.",
            user_text="one line of chicken",
            model="mistral-medium-latest",
        )
        body = _Client.posts[0]["json"]
        self.assertEqual(body["max_tokens"], llm_provider.INGEST_MAX_TOKENS)
        self.assertEqual(llm_provider.mistral_payload_issues(body), [])

    def test_non_2xx_logs_the_mistral_message_and_not_the_key(self):
        _Client.response = _error_response(
            400,
            {
                "object": "error",
                "message": f"prompt plus max_tokens exceeds context {KEY}",
                "type": "invalid_request_error",
                "code": "context_length_exceeded",
                "param": "max_tokens",
            },
        )
        with self.assertLogs("catalog.llm_provider", level="WARNING") as logs:
            with self.assertRaises(llm_provider.MistralHTTPError) as caught:
                llm_provider.chat_completion_json(
                    system="Reply as JSON.",
                    user_text="Hello",
                    model="mistral-large-latest",
                    max_tokens=128,
                )
        text = "\n".join(logs.output)
        self.assertIn("HTTP 400", text)
        self.assertIn("prompt plus max_tokens exceeds context", text)
        self.assertIn("context_length_exceeded", text)
        self.assertIn("mistral-large-latest", text)
        self.assertIn("[redacted]", text)
        self.assertNotIn(KEY, text)
        self.assertNotIn("Authorization", text)
        self.assertNotIn("Bearer", text)
        self.assertEqual(caught.exception.status_code, 400)
        self.assertNotIn(KEY, caught.exception.provider_message)
        # The request header was on the response, and must not be in the log.
        self.assertIn("Authorization", _Client.posts[0]["headers"])

    def test_upstream_400_is_a_friendly_companion_error(self):
        with patch.object(companion, "_require_key", lambda: None):
            with patch.object(
                companion.llm_provider,
                "chat_completion_json",
                side_effect=llm_provider.MistralHTTPError(
                    400, f"bad payload {KEY}"
                ),
            ):
                with self.assertRaises(companion.CompanionError) as caught:
                    companion._call("sys", "user")
        self.assertEqual(caught.exception.code, "llm_rejected")
        self.assertNotIn(KEY, str(caught.exception))
        self.assertNotIn("bad payload", str(caught.exception))
        self.assertIn("shorter", str(caught.exception))

    def _posted(self, **kwargs) -> dict:
        _Client.posts.clear()
        llm_provider.chat_completion_json(
            system="Reply as JSON.",
            user_text="Fire the jus.",
            model="mistral-large-latest",
            max_tokens=128,
            **kwargs,
        )
        self.assertEqual(len(_Client.posts), 1)
        return _Client.posts[0]["json"]

    def test_temperature_zero_sends_top_p_one(self):
        """The live 400: temperature 0 and no top_p (code 3054).

        Greedy sampling is only valid with top_p exactly 1, including when a
        caller passed some other nucleus or a temperature that clamps to 0.
        """
        cases = [
            {},
            {"temperature": 0},
            {"temperature": 0, "top_p": 0.2},
            {"temperature": 0.0, "top_p": 0},
            {"temperature": -4, "top_p": 0.9},
            {"temperature": float("nan"), "top_p": 5},
            {"temperature": "0", "top_p": None},
        ]
        for kwargs in cases:
            body = self._posted(**kwargs)
            self.assertEqual(body["temperature"], 0, kwargs)
            self.assertEqual(body["top_p"], 1, kwargs)
            self.assertEqual(llm_provider.mistral_payload_issues(body), [], kwargs)

    def test_nonzero_temperature_clamps_top_p(self):
        kept = self._posted(temperature=0.4, top_p=0.3)
        self.assertEqual(kept["temperature"], 0.4)
        self.assertEqual(kept["top_p"], 0.3)
        self.assertEqual(llm_provider.mistral_payload_issues(kept), [])

        capped = self._posted(temperature=0.4, top_p=5)
        self.assertEqual(capped["top_p"], 1)
        self.assertEqual(llm_provider.mistral_payload_issues(capped), [])

        # temperature 9 clamps to the API maximum and is not greedy, so a
        # legal top_p is left alone.
        warm = self._posted(temperature=9, top_p=0.25)
        self.assertEqual(warm["temperature"], llm_provider.TEMPERATURE_MAX)
        self.assertEqual(warm["top_p"], 0.25)
        self.assertEqual(llm_provider.mistral_payload_issues(warm), [])

        defaulted = self._posted(temperature=0.6)
        self.assertEqual(defaulted["top_p"], 1)

        parsed = self._posted(temperature=0.6, top_p="0.8")
        self.assertEqual(parsed["top_p"], 0.8)

        for raw in (0, -3, "0"):
            opened = self._posted(temperature=0.2, top_p=raw)
            self.assertGreater(opened["top_p"], 0, raw)
            self.assertLessEqual(opened["top_p"], 1, raw)
            self.assertEqual(opened["top_p"], math.nextafter(0.0, 1.0), raw)
            self.assertEqual(llm_provider.mistral_payload_issues(opened), [], raw)

    def test_greedy_payload_without_top_p_is_invalid(self):
        bare = {
            "model": "mistral-large-latest",
            "temperature": 0,
            "max_tokens": 128,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": "Reply as JSON."},
                {"role": "user", "content": "Hello"},
            ],
        }
        self.assertIn("top_p", llm_provider.mistral_payload_issues(bare))
        bare["top_p"] = 0.9
        self.assertIn("top_p", llm_provider.mistral_payload_issues(bare))
        bare["top_p"] = 1
        self.assertEqual(llm_provider.mistral_payload_issues(bare), [])
        warm = {**bare, "temperature": 0.4, "top_p": 0}
        self.assertIn("top_p", llm_provider.mistral_payload_issues(warm))
        warm["top_p"] = 0.4
        self.assertEqual(llm_provider.mistral_payload_issues(warm), [])

    def test_companion_chat_payload_passes(self):
        with (
            patch.object(companion, "build_day_context", lambda d: {"sections": []}),
            patch.object(companion, "build_house_stock_context", lambda: {}),
            patch.object(companion, "get_profile", lambda: {"text": "", "updated_at": None}),
        ):
            out = companion.companion_chat(
                [{"role": "user", "content": "What should I fire first?"}],
                date(2026, 11, 17),
            )
        self.assertEqual(out["reply"], "Fire the jus.")
        body = _Client.posts[0]["json"]
        self.assertEqual(body["temperature"], 0)
        self.assertEqual(body["top_p"], 1)
        self.assertEqual(body["max_tokens"], llm_provider.COMPANION_MAX_TOKENS)
        self.assertEqual(body["model"], "mistral-large-latest")
        self.assertEqual(llm_provider.mistral_payload_issues(body), [])

    def test_recipe_draft_payload_passes(self):
        _Client.response = _content_response(
            json.dumps(
                {
                    "name": "Chicken jus",
                    "base_covers": 20,
                    "ingredients": [
                        {"name": "chicken", "qty": 2, "unit": "kg", "note": ""}
                    ],
                    "method": ["Reduce the stock."],
                    "allergens": ["celery"],
                    "notes": "Batch for 20.",
                }
            )
        )
        with patch.object(
            companion, "get_profile", lambda: {"text": "", "updated_at": None}
        ):
            card = companion.draft_recipe("chicken jus for service", covers=20)
        self.assertEqual(card["name"], "Chicken jus")
        self.assertEqual(card["allergens"], ["celery"])
        body = _Client.posts[0]["json"]
        self.assertEqual(body["temperature"], 0)
        self.assertEqual(body["top_p"], 1)
        self.assertEqual(body["max_tokens"], llm_provider.COMPANION_MAX_TOKENS)
        self.assertEqual(body["model"], "mistral-large-latest")
        self.assertEqual(llm_provider.mistral_payload_issues(body), [])

    def test_ingest_payload_passes(self):
        text = ingest._call_llm_strict_json(
            {"text": "chicken thigh 2 kg", "images": None},
            model="mistral-medium-latest",
        )
        self.assertIn("Fire the jus", text)
        body = _Client.posts[0]["json"]
        self.assertEqual(body["temperature"], 0)
        self.assertEqual(body["top_p"], 1)
        self.assertEqual(body["max_tokens"], llm_provider.INGEST_MAX_TOKENS)
        self.assertEqual(body["model"], "mistral-medium-latest")
        self.assertEqual(llm_provider.mistral_payload_issues(body), [])
