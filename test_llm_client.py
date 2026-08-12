"""
Which credential a model route authenticates with.

Read from the environment rather than by constructing a client: the Anthropic SDK
constructs happily with no key and defers the failure to the first call, so asking
the client would have answered "fine" for the one route that was broken.
"""


from subversionbench.llm_client import credential_env_var, missing_credential
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
