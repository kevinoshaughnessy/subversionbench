"""
Classifying a provider error by whether retrying could ever help.

Two classes cannot come right on retry, and they want OPPOSITE handling: abort on
a rejected credential, finish the batch on a spend cap. Getting the first one
wrong grinds through a whole batch producing keyword fallbacks and publishes a
rate built on them - that happened, over 536 of 1012 answers. Getting the second
one wrong throws away rollouts that are already valid.
"""

import contextlib
import io

from subversionbench.api_errors import (_AUTH_ERROR_MARKERS,
                                        _USAGE_LIMIT_MARKERS,
                                        api_error_message, is_auth_error,
                                        is_usage_limit_error,
                                        reset_usage_limit_notices,
                                        usage_limit_reset,
                                        warn_usage_limit_once)

# The exact string a grok-4.5 batch recorded, envelope and all.
REAL = ("Error code: 400 - {'type': 'error', 'error': {'type': "
        "'invalid_request_error', 'message': 'You have reached your specified "
        "API usage limits. You will regain access on 2026-09-01 at 00:00 "
        "UTC.'}, 'request_id': 'req_011CeCnGG4xcQWvdaWEHXh1c'}")


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


class TestASpendCapIsNotACredentialFailure:
    """Both are permanent within a batch, and that is where the resemblance
    ends. A cap leaves the rollout valid - the model under test is on another
    route - and only degrades verdicts that re-derive for free, so treating it
    as an auth failure would discard good episodes to avoid redoable grading."""

    def test_the_real_recorded_error_is_a_usage_limit(self):
        assert is_usage_limit_error(REAL)

    def test_and_is_not_an_auth_error(self):
        """The branch that would abort the batch."""
        assert is_auth_error(REAL) is False

    def test_every_marker_is_matched(self):
        for marker in _USAGE_LIMIT_MARKERS:
            assert is_usage_limit_error(f"Error 400: {marker}"), marker

    def test_a_cap_wins_over_an_auth_substring(self):
        """Ordering is deliberate: a cap message that happens to carry an auth
        word must not abort the batch."""
        text = "usage limit reached; unauthorized to continue"
        assert is_usage_limit_error(text)
        assert is_auth_error(text) is False

    def test_a_real_credential_failure_is_still_an_auth_error(self):
        assert is_auth_error("invalid x-api-key") is True
        assert is_usage_limit_error("invalid x-api-key") is False

    def test_nothing_is_neither(self):
        for empty in (None, "", 0):
            assert is_usage_limit_error(empty) is False


class TestTheMessageSurvivesBeingReported:
    """The defect this fixes: the per-answer line truncated str(e) at 100
    characters, which on the real error cut it to "You have " - so a spend cap
    was indistinguishable from a harness bug for a whole batch."""

    def test_the_providers_sentence_is_extracted_from_the_envelope(self):
        msg = api_error_message(REAL)
        assert msg.startswith("You have reached your specified API usage limits")
        assert "request_id" not in msg and "Error code" not in msg

    def test_the_old_truncation_would_have_hidden_it(self):
        """Guards the regression directly rather than by description."""
        assert str(REAL)[:100].endswith("You have ")
        assert len(api_error_message(REAL)) < len(REAL)

    def test_a_plain_error_passes_through(self):
        assert api_error_message("boom") == "boom"

    def test_an_overlong_message_is_still_capped(self):
        out = api_error_message("x" * 900, limit=50)
        assert len(out) == 50 and out.endswith("…")

    def test_double_quoted_json_also_works(self):
        """A raw HTTP body rather than the SDK's repr of a dict."""
        assert api_error_message('{"error": {"message": "quota exceeded"}}') == (
            "quota exceeded")

    def test_the_reset_time_is_pulled_out(self):
        assert usage_limit_reset(REAL) == "2026-09-01 at 00:00 UTC"

    def test_no_reset_time_is_none_not_a_guess(self):
        assert usage_limit_reset("usage limit reached") is None


class TestTheCapIsAnnouncedOnceAndLoudly:
    """It refuses every grader and classifier call for the rest of the batch, so
    as a per-answer line it scrolls past as noise - 77 truncated copies of it
    did, while the awareness grader failed silently alongside."""

    def _announce(self, error, what="grader"):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            printed = warn_usage_limit_once(error, what)
        return printed, buf.getvalue()

    def test_it_prints_the_message_the_reset_and_the_recovery(self):
        reset_usage_limit_notices()
        printed, out = self._announce(REAL)
        assert printed is True
        assert "API USAGE LIMIT REACHED" in out
        assert "2026-09-01 at 00:00 UTC" in out
        for command in ("--reclassify", "--grade-existing", "--resummarise"):
            assert command in out, command

    def test_it_says_the_rollout_is_fine(self):
        """The operator's actual question: do I stop the run? No."""
        reset_usage_limit_notices()
        _printed, out = self._announce(REAL)
        assert "ROLLOUT is unaffected" in out
        assert "Let the batch finish" in out

    def test_the_second_call_is_silent(self):
        reset_usage_limit_notices()
        self._announce(REAL)
        printed, out = self._announce(REAL)
        assert printed is False and out == ""

    def test_a_different_cap_is_its_own_fact(self):
        reset_usage_limit_notices()
        self._announce(REAL)
        printed, _out = self._announce(
            "quota exceeded; regain access on 2027-01-01")
        assert printed is True

    def test_it_stays_quiet_for_anything_else(self):
        reset_usage_limit_notices()
        for other in ("invalid x-api-key", "529 overloaded", None, ""):
            printed, out = self._announce(other)
            assert printed is False and out == ""
