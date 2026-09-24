"""
The OpenCode route: what makes it different from OpenRouter, since
everything else (create(), the response-block parsing, the non-JSON and
no-choices diagnostics) is inherited from OpenRouterClient unchanged and is
already covered by test_openrouter_client.py against the same code paths.

Three things are actually new here: which credential and base URL it uses,
that a vendor-prefixed model id is stripped to Zen's own bare id before it
reaches the wire, and that OpenRouter's `provider` routing dict is never
built at all.

Run: pytest test_opencode_client.py -v
"""

import os

import pytest


class TestOpencodeConstruction:
    def setup_method(self, method):
        from conftest import skip_without
        skip_without("openai", "needed by the OpenRouter/OpenCode routes")

    def test_raises_without_a_credential(self):
        from conftest import env_without
        from subversionbench.opencode_client import OpenCodeClient

        with env_without("OPENCODE_API_KEY"):
            with pytest.raises(RuntimeError, match="OPENCODE_API_KEY"):
                OpenCodeClient()

    def test_points_at_the_opencode_base_url(self):
        from subversionbench.config import OPENCODE_BASE_URL
        from subversionbench.opencode_client import OpenCodeClient

        os.environ.setdefault("OPENCODE_API_KEY", "dummy")
        client = OpenCodeClient()
        assert str(client._client.base_url).rstrip("/") == OPENCODE_BASE_URL

    def test_carries_no_openrouter_provider_routing(self):
        """Duck-type identical to OpenRouterClient for any caller that reads
        these attributes without checking the class - OpenCode has no
        equivalent of either, so both stay unconditionally unset."""
        from subversionbench.opencode_client import OpenCodeClient

        os.environ.setdefault("OPENCODE_API_KEY", "dummy")
        client = OpenCodeClient()
        assert client._provider_sort is None
        assert client._provider_name is None


class TestOpencodeModelIdTranslation:
    def test_strips_the_vendor_prefix(self):
        from subversionbench.opencode_client import _opencode_model_id
        assert _opencode_model_id("x-ai/grok-4.5") == "grok-4.5"
        assert _opencode_model_id("deepseek/deepseek-v4.1-flash") == \
            "deepseek-v4.1-flash"

    def test_a_bare_id_passes_through_unchanged(self):
        from subversionbench.opencode_client import _opencode_model_id
        assert _opencode_model_id("claude-opus-5") == "claude-opus-5"


class TestOpencodeRequestShape:
    def setup_method(self, method):
        from conftest import skip_without
        skip_without("openai", "needed by the OpenRouter/OpenCode routes")

    def _client(self):
        from subversionbench.opencode_client import OpenCodeClient
        os.environ.setdefault("OPENCODE_API_KEY", "dummy")
        return OpenCodeClient()

    def test_the_wire_model_id_is_zens_bare_one(self):
        kwargs = self._client()._request_kwargs(
            "x-ai/grok-4.5", 100, "sys", None,
            [{"role": "user", "content": "hi"}])
        assert kwargs["model"] == "grok-4.5"

    def test_no_provider_routing_dict_is_ever_sent(self):
        """OpenRouterClient adds extra_body.provider (require_parameters at
        minimum, whenever tools are present) - Zen has no documented
        equivalent, so OpenCodeClient must never send it, tools or not."""
        client = self._client()
        tools = [{"name": "bash", "description": "d",
                  "input_schema": {"type": "object"}}]
        kwargs = client._request_kwargs(
            "x-ai/grok-4.5", 100, "sys", tools,
            [{"role": "user", "content": "hi"}])
        assert "extra_body" not in kwargs
        assert kwargs["tools"] == [{
            "type": "function",
            "function": {"name": "bash", "description": "d",
                        "parameters": {"type": "object"}},
        }]

    def test_error_diagnostics_name_opencode_not_openrouter(self):
        """_completion()'s two diagnostics are inherited from
        OpenRouterClient and used to hardcode "OpenRouter" even when the
        request actually went to Zen - _GATEWAY_NAME fixes that."""
        from unittest.mock import MagicMock

        client = self._client()
        client._client = MagicMock()
        fake_raw = MagicMock()
        fake_raw.status_code = 500
        fake_raw.text = "<html>error</html>"

        import json
        fake_raw.parse.side_effect = json.JSONDecodeError("x", "x", 0)
        client._client.chat.completions.with_raw_response.create.return_value = fake_raw

        with pytest.raises(RuntimeError, match="OpenCode returned a non-JSON") as exc:
            client.create(model="x-ai/grok-4.5", max_tokens=100,
                          messages=[{"role": "user", "content": "hi"}])
        assert "OpenRouter" not in str(exc.value)
