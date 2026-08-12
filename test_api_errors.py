"""
Classifying a provider error by whether retrying could ever help.

One class matters here and it is the reason the module exists: a missing or
rejected credential fails identically on call 1 and call 500, so a caller that
treats it as transient grinds through a whole batch producing keyword fallbacks
and publishes a rate built on them. That happened, over 536 of 1012 answers, and
it is what these tests protect against recurring.
"""

from subversionbench.api_errors import _AUTH_ERROR_MARKERS, is_auth_error


class TestACredentialFailureIsRecognised:
    def test_every_marker_is_matched(self):
        """Each entry was added because a real provider produced it. A marker
        nobody matches is a route whose failure would be treated as transient."""
        for marker in _AUTH_ERROR_MARKERS:
            assert is_auth_error(f"Error: {marker} (request id abc)"), marker

    def test_matching_ignores_case(self):
        """Providers differ on capitalisation, and the same provider differs
        between its SDK exception and its HTTP body."""
        assert is_auth_error("AUTHENTICATION_ERROR: invalid X-API-Key")
        assert is_auth_error("Unauthorized")

    def test_an_exception_object_is_accepted_not_just_a_string(self):
        """Callers pass whatever the SDK raised. Requiring str() at every call
        site is one place to forget it."""
        assert is_auth_error(RuntimeError("401 Unauthorized"))

    def test_the_anthropic_sdk_wording_is_covered(self):
        """The exact text of the failure that produced the incident: the SDK
        constructs happily with no key and defers to the first call."""
        assert is_auth_error(
            "Could not resolve authentication method. Expected either api_key "
            "or auth_token to be set.")


class TestEverythingElseIsLeftAlone:
    def test_no_error_is_not_an_auth_error(self):
        """Called on the error field of a result that may not have one, so None
        and empty string have to be safe rather than truthy."""
        for falsy in (None, "", 0, [], {}):
            assert is_auth_error(falsy) is False, falsy

    def test_a_transient_failure_is_not_misread_as_terminal(self):
        """Aborting on one of these would throw away a batch that would have
        completed on retry - the opposite failure, and just as expensive."""
        for transient in ("rate_limit_error: slow down",
                          "overloaded_error", "500 internal server error",
                          "read timeout", "connection reset by peer",
                          "invalid_request_error: max_tokens too large"):
            assert is_auth_error(transient) is False, transient

    def test_the_status_code_is_matched_as_a_number_not_a_substring(self):
        """It was a substring, so "used 4013 input tokens" was an authentication
        failure - and this class aborts the batch on its first occurrence, so a
        false positive throws away the rest of a rollout.

        The same mistake as the awareness matcher, where "to see how i" matched
        inside "to see how it"."""
        for not_auth in ("used 4013 input tokens", "offset 1401 in the file",
                         "40100 tokens", "budget 24010"):
            assert is_auth_error(not_auth) is False, not_auth
        for auth in ("HTTP 401", "status=401, body=...", "got 401 back",
                     "Error code: 401"):
            assert is_auth_error(auth) is True, auth
