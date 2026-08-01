"""
Classifying provider errors by whether retrying could ever help.

Separated because the answer drives control flow rather than reporting: a
credentials failure is the one class that cannot come right on retry and is
never partial, so callers abort on the first one instead of grinding through a
batch producing fallbacks.
"""

_AUTH_ERROR_MARKERS = (
    "could not resolve authentication method",
    "authentication_error",
    "invalid x-api-key",
    "invalid api key",
    "no api key",
    "api key not found",
    "incorrect api key",
    "unauthorized",
    "401",
)


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
    return any(marker in text for marker in _AUTH_ERROR_MARKERS)


