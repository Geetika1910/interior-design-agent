"""Zero-cost tests for the 429 rate-limit retry logic in src/agent.py.
Mocks the OpenAI client and time.sleep — no real API calls, no real waiting.
"""
from unittest.mock import MagicMock, patch

import httpx2
from openai import RateLimitError

from src.agent import RATE_LIMIT_RETRIES, _RateLimitExhausted, _create_completion_with_retry


def _make_429(retry_after=None):
    headers = {"retry-after": str(retry_after)} if retry_after else {}
    response = httpx2.Response(status_code=429, headers=headers, request=httpx2.Request("POST", "https://x"))
    return RateLimitError("rate limited", response=response, body=None)


def test_retries_transparently_then_succeeds():
    fake_success = MagicMock()
    calls = []

    def side_effect(*args, **kwargs):
        calls.append(1)
        if len(calls) <= 2:
            raise _make_429(retry_after=0.01)
        return fake_success

    with patch("time.sleep"):
        client = MagicMock()
        client.chat.completions.create.side_effect = side_effect
        result = _create_completion_with_retry(client, [{"role": "user", "content": "hi"}])

    assert result is fake_success
    assert len(calls) == 3


def test_raises_exhausted_after_max_retries():
    calls = []

    def always_fail(*args, **kwargs):
        calls.append(1)
        raise _make_429()

    with patch("time.sleep"):
        client = MagicMock()
        client.chat.completions.create.side_effect = always_fail
        try:
            _create_completion_with_retry(client, [{"role": "user", "content": "hi"}])
            assert False, "should have raised _RateLimitExhausted"
        except _RateLimitExhausted:
            pass

    assert len(calls) == RATE_LIMIT_RETRIES + 1


def test_respects_retry_after_header():
    fake_success = MagicMock()
    calls = []

    def fail_once(*args, **kwargs):
        calls.append(1)
        if len(calls) == 1:
            raise _make_429(retry_after=7)
        return fake_success

    with patch("time.sleep") as mock_sleep:
        client = MagicMock()
        client.chat.completions.create.side_effect = fail_once
        _create_completion_with_retry(client, [{"role": "user", "content": "hi"}])

    mock_sleep.assert_called_once_with(7.0)


if __name__ == "__main__":
    import sys
    from tests._runner import run_module
    ok = run_module(sys.modules[__name__])
    sys.exit(0 if ok else 1)
