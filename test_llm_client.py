"""
Which credential a model route authenticates with.

Read from the environment rather than by constructing a client: the Anthropic SDK
constructs happily with no key and defers the failure to the first call, so asking
the client would have answered "fine" for the one route that was broken.
"""


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


class TestProviderSortRouting:
    """--openrouter-sort only means anything on the OpenRouter branch - the
    other two routes take no such concept, so get_client() must accept and
    silently drop it rather than erroring."""

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
