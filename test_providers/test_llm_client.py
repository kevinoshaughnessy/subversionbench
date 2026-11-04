"""
Which credential a model route authenticates with.

Read from the environment rather than by constructing a client: the Anthropic SDK
constructs happily with no key and defers the failure to the first call, so asking
the client would have answered "fine" for the one route that was broken.
"""


import contextlib
import os

from subversionbench.llm_client import credential_env_var, get_client, missing_credential
from conftest import env_without


class TestTheRouteToCredentialMapping:
    def test_each_route_names_its_own_variable(self):
        assert credential_env_var("claude-opus-5") == "ANTHROPIC_API_KEY"
        assert credential_env_var("x-ai/grok-4.5") == "OPENROUTER_API_KEY"
        assert credential_env_var("gpt-5.6-sol") == "OPENAI_API_KEY"

    def test_present_means_none_missing(self):
        assert missing_credential("claude-opus-5") is None

    def test_absent_is_reported_by_name(self):
        with env_without("ANTHROPIC_API_KEY"):
            assert missing_credential("claude-opus-5") == "ANTHROPIC_API_KEY"

    def test_it_reads_the_environment_rather_than_building_a_client(self):
        """The three routes fail at different times: the OpenRouter and OpenAI
        clients raise at construction, while anthropic.Anthropic() builds happily
        with no key and defers the failure to the first call. Checking the
        environment is uniform across routes, costs nothing, and cannot itself
        fail."""
        import inspect
        from subversionbench import llm_client
        src = inspect.getsource(llm_client.missing_credential)
        assert "os.environ" in src
        assert "get_client" not in src


class TestTheOpencodeCredentialMapping:
    """use_opencode changes WHICH credential an OpenRouter-shaped id needs -
    the same "provider/model" id authenticates with a different variable
    depending on which gateway --use-opencode picked, so the pre-flight
    check has to be told the same choice the client will actually make."""

    def test_use_opencode_names_its_own_variable(self):
        assert credential_env_var("x-ai/grok-4.5", use_opencode=True) == \
            "OPENCODE_API_KEY"

    def test_without_it_the_route_is_unchanged(self):
        assert credential_env_var("x-ai/grok-4.5", use_opencode=False) == \
            "OPENROUTER_API_KEY"

    def test_use_opencode_does_not_change_a_non_openrouter_route(self):
        """A bare id never reaches OpenCode regardless of the flag - the
        same "not applicable" case is_openrouter_model already governs for
        provider_sort/provider_name."""
        assert credential_env_var("claude-opus-5", use_opencode=True) == \
            "ANTHROPIC_API_KEY"
        assert credential_env_var("gpt-5.6-sol", use_opencode=True) == \
            "OPENAI_API_KEY"

    def test_absent_is_reported_by_name(self):
        with env_without("OPENCODE_API_KEY"):
            assert missing_credential("x-ai/grok-4.5", use_opencode=True) == \
                "OPENCODE_API_KEY"


class TestProviderSortRouting:
    """--openrouter-sort only means anything on the OpenRouter branch - the
    other two routes take no such concept, so get_client() must accept and
    silently drop it rather than erroring."""

    def setup_method(self, method):
        """`openai` is an optional extra, imported lazily by the client. Without
        this these tests raised ModuleNotFoundError instead of skipping, so a
        clean `pip install -e .[test]` could not produce a green suite."""
        from conftest import skip_without
        skip_without("openai", "needed by the OpenRouter/OpenAI routes")


    def test_reaches_the_openrouter_client_when_the_model_routes_there(self):
        os.environ.setdefault("OPENROUTER_API_KEY", "dummy")
        client = get_client("x-ai/grok-4.5", provider_sort="throughput")
        assert client._provider_sort == "throughput"

    def test_defaults_to_none_when_not_requested(self):
        os.environ.setdefault("OPENROUTER_API_KEY", "dummy")
        client = get_client("x-ai/grok-4.5")
        assert client._provider_sort is None

    def test_silently_dropped_for_a_native_anthropic_model(self):
        # Would raise TypeError if get_client forwarded provider_sort to
        # anthropic.Anthropic(), which has no such parameter.
        get_client("claude-opus-5", provider_sort="throughput")


class TestProviderPinningRouting:
    """--openrouter-provider, same story as --openrouter-sort above: only the
    OpenRouter branch understands it, the other two routes must accept and
    drop it."""

    def setup_method(self, method):
        """`openai` is an optional extra, imported lazily by the client. Without
        this these tests raised ModuleNotFoundError instead of skipping, so a
        clean `pip install -e .[test]` could not produce a green suite."""
        from conftest import skip_without
        skip_without("openai", "needed by the OpenRouter/OpenAI routes")


    def test_reaches_the_openrouter_client_when_the_model_routes_there(self):
        os.environ.setdefault("OPENROUTER_API_KEY", "dummy")
        client = get_client("x-ai/grok-4.5", provider_name="deepinfra")
        assert client._provider_name == "deepinfra"

    def test_defaults_to_none_when_not_requested(self):
        os.environ.setdefault("OPENROUTER_API_KEY", "dummy")
        client = get_client("x-ai/grok-4.5")
        assert client._provider_name is None

    def test_silently_dropped_for_a_native_anthropic_model(self):
        get_client("claude-opus-5", provider_name="deepinfra")


class TestOpencodeRouting:
    """--use-opencode picks OpenCodeClient over OpenRouterClient for the same
    OpenRouter-shaped ids - a different gateway, not a new id shape - and
    must be silently dropped for a route that never reaches either client,
    the same story --openrouter-sort/--openrouter-provider already have."""

    def setup_method(self, method):
        from conftest import skip_without
        skip_without("openai", "needed by the OpenRouter/OpenAI routes")

    def test_reaches_the_opencode_client_when_requested(self):
        from subversionbench.opencode_client import OpenCodeClient
        os.environ.setdefault("OPENCODE_API_KEY", "dummy")
        client = get_client("x-ai/grok-4.5", use_opencode=True)
        assert isinstance(client, OpenCodeClient)

    def test_reaches_the_openrouter_client_by_default(self):
        from subversionbench.opencode_client import OpenCodeClient
        os.environ.setdefault("OPENROUTER_API_KEY", "dummy")
        client = get_client("x-ai/grok-4.5")
        assert not isinstance(client, OpenCodeClient)

    def test_silently_dropped_for_a_native_anthropic_model(self):
        # Would raise TypeError if get_client forwarded use_opencode to
        # anthropic.Anthropic(), which has no such parameter - and must
        # return the native client, not OpenCodeClient, since the route
        # never changes for a non-OpenRouter id.
        from subversionbench.opencode_client import OpenCodeClient
        client = get_client("claude-opus-5", use_opencode=True)
        assert not isinstance(client, OpenCodeClient)


class TestTheModelUnderTestGetsALongerTimeout:
    """At --effort max a turn of the model under test can think past 90s,
    the limit the short grader calls get. claude-sonnet-4-6 lost 5 of 30 max
    episodes to it, at turns 4-7 - the longest deliberations, so the loss was
    a selection rather than noise. Checked through the function episode.py
    actually builds its client with, so a call site that stopped widening it
    fails here."""

    def test_a_claude_episode_client_waits_longer_than_a_grader_call(self):
        import subversionbench.episode as ep
        from subversionbench.llm_client import (
            ANTHROPIC_MODEL_TURN_TIMEOUT_S, ANTHROPIC_SHORT_CALL_TIMEOUT_S)
        grader = get_client("claude-sonnet-4-6")
        under_test, *_ = ep._resolved_routing("claude-sonnet-4-6", None, None,
                                              False)
        assert grader.timeout == ANTHROPIC_SHORT_CALL_TIMEOUT_S
        assert under_test.timeout == ANTHROPIC_MODEL_TURN_TIMEOUT_S
        assert ANTHROPIC_MODEL_TURN_TIMEOUT_S > ANTHROPIC_SHORT_CALL_TIMEOUT_S

    def test_every_claude_request_asks_for_the_pinned_api_version(self):
        """anthropic 2.x asks for a newer API version by default, which can
        change what the server returns - thinking text included. Read off the
        request each client actually sends, so an SDK that ignored the header
        fails here."""
        import json
        import sys
        from unittest import mock

        import httpx
        import subversionbench.episode as ep
        from subversionbench.llm_client import ANTHROPIC_API_VERSION
        sent = []

        def send(self, request, *args, **kwargs):
            sent.append(request.headers.get("anthropic-version"))
            module = sys.modules[type(request).__module__.split(".")[0]]
            return module.Response(200, request=request, json={
                "id": "m", "type": "message", "role": "assistant",
                "model": "claude-sonnet-4-6", "stop_reason": "end_turn",
                "content": [{"type": "text", "text": "ok"}],
                "usage": {"input_tokens": 1, "output_tokens": 1}})

        transports = [httpx] + [sys.modules[n] for n in ("httpx2",)
                                if n in sys.modules]
        under_test, *_ = ep._resolved_routing("claude-sonnet-4-6", None, None,
                                              False)
        with contextlib.ExitStack() as stack:
            for t in transports:
                stack.enter_context(mock.patch.object(t.Client, "send", send))
            for client in (get_client("claude-sonnet-4-6"), under_test):
                client.messages.create(
                    model="claude-sonnet-4-6", max_tokens=8,
                    messages=[{"role": "user", "content": "hi"}])
        assert sent == [ANTHROPIC_API_VERSION] * 2, json.dumps(sent)

    def test_any_other_client_comes_back_unchanged(self):
        """An OpenRouter or OpenAI client, or a test's stand-in, is not an
        Anthropic SDK client and must not be touched."""
        from subversionbench.llm_client import for_model_under_test
        stand_in = object()
        assert for_model_under_test(stand_in) is stand_in
