"""
Classifying provider errors by whether retrying could ever help.

Separated because the answer drives control flow rather than reporting: a
credentials failure is the one class that cannot come right on retry and is
never partial, so callers abort on the first one instead of grinding through a
batch producing fallbacks.
"""

import re

_AUTH_ERROR_MARKERS = (
    "could not resolve authentication method",
    "authentication_error",
    "invalid x-api-key",
    "invalid api key",
    "no api key",
    "api key not found",
    "incorrect api key",
    "unauthorized",
)

# The status code, matched as a NUMBER rather than as a substring.
#
# It was in the list above, so "used 4013 input tokens" was an authentication
# failure. This class of error aborts the batch on its first occurrence by design,
# which is exactly what makes a false positive expensive: any error text that
# happened to contain those three digits would throw away the rest of a rollout.
#
# The same substring-versus-token mistake as the awareness matcher, where
# "to see how i" matched inside "to see how it" and moved first-awareness to
# roughly the first command in 60 episodes that verbalise none.
_AUTH_STATUS_RE = re.compile(r"(?<!\d)401(?!\d)")


def is_auth_error(error) -> bool:
    """
    Whether `error` is a missing or rejected credential.

    Worth separating from every other API failure because it is the one class
    that cannot come right on retry and is never partial: an unexported key
    fails identically on call 1 and call 500. A caller that treats it as a
    transient error will grind through a whole batch producing fallbacks, so
    the honest response is to stop on the first one.
    """
    if not error:
        return False
    text = str(error).lower()
    return (any(marker in text for marker in _AUTH_ERROR_MARKERS)
            or _AUTH_STATUS_RE.search(text) is not None)


