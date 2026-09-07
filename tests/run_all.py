"""Run every zero-cost local test — no API calls, no network. Use this for
routine verification instead of spending API credits.

Usage: python -m tests.run_all
"""
import sys

from tests import (
    test_tools, test_validation, test_scorers, test_agent_retry,
    test_malformed_submission, test_verification_guardrail,
)
from tests._runner import run_module

if __name__ == "__main__":
    results = [run_module(m) for m in (
        test_tools, test_validation, test_scorers, test_agent_retry,
        test_malformed_submission, test_verification_guardrail,
    )]
    if all(results):
        print("ALL LOCAL TESTS PASSED (zero API calls made)")
        sys.exit(0)
    else:
        print("SOME LOCAL TESTS FAILED")
        sys.exit(1)
