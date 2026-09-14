"""Retry policy override for podcast-creator 0.12.0.

LangChain's OutputParserException inherits from ValueError.  The upstream
policy treats every ValueError as a programming/input error, which makes a
transient malformed LLM response bypass the configured retry loop entirely.
Keep ordinary ValueError failures fail-fast, but retry structured-output
parsing failures with the library's existing bounded backoff.
"""

import os
from typing import Any, Dict, Optional

from langchain_core.exceptions import OutputParserException
from loguru import logger
from tenacity import (
    RetryCallState,
    retry,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential,
)

DEFAULT_MAX_ATTEMPTS = 3
DEFAULT_WAIT_MULTIPLIER = 5
DEFAULT_WAIT_MAX = 30

NON_RETRYABLE_EXCEPTIONS = (
    ValueError,
    TypeError,
    KeyError,
    FileNotFoundError,
    AssertionError,
)


def _log_retry(retry_state: RetryCallState) -> None:
    exception = retry_state.outcome.exception() if retry_state.outcome else None
    wait = retry_state.next_action.sleep if retry_state.next_action else 0
    logger.warning(
        f"Retry attempt {retry_state.attempt_number} failed with "
        f"{type(exception).__name__}: {exception}. "
        f"Waiting {wait:.1f}s before next attempt."
    )


def get_retry_config(configurable: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    configurable = configurable or {}
    max_attempts = (
        configurable.get("retry_max_attempts")
        or _int_env("PODCAST_RETRY_MAX_ATTEMPTS")
        or DEFAULT_MAX_ATTEMPTS
    )
    wait_multiplier = (
        configurable.get("retry_wait_multiplier")
        or _int_env("PODCAST_RETRY_WAIT_MULTIPLIER")
        or DEFAULT_WAIT_MULTIPLIER
    )
    wait_max = (
        configurable.get("retry_wait_max")
        or _int_env("PODCAST_RETRY_WAIT_MAX")
        or DEFAULT_WAIT_MAX
    )
    return {
        "max_attempts": int(max_attempts),
        "wait_multiplier": int(wait_multiplier),
        "wait_max": int(wait_max),
    }


def _int_env(name: str) -> Optional[int]:
    value = os.environ.get(name)
    return int(value) if value is not None else None


def _is_retryable(exception: BaseException) -> bool:
    # Must precede the ValueError family check: OutputParserException is a
    # ValueError subclass, but malformed provider JSON is transient and safe
    # to retry because this happens before an episode is accepted/persisted.
    if isinstance(exception, OutputParserException):
        return True
    if isinstance(exception, NON_RETRYABLE_EXCEPTIONS):
        return False
    status_code = getattr(exception, "status_code", None)
    if status_code is not None and 400 <= status_code < 500 and status_code != 429:
        return False
    return True


def create_retry_decorator(
    max_attempts: int = DEFAULT_MAX_ATTEMPTS,
    wait_multiplier: int = DEFAULT_WAIT_MULTIPLIER,
    wait_max: int = DEFAULT_WAIT_MAX,
) -> Any:
    return retry(
        stop=stop_after_attempt(max_attempts),
        wait=wait_exponential(multiplier=wait_multiplier, max=wait_max),
        retry=retry_if_exception(_is_retryable),
        before_sleep=_log_retry,
        reraise=True,
    )
