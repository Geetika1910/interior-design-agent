"""Tiny zero-dependency test runner: no pytest, just plain functions named
test_* that raise AssertionError on failure. Deliberately minimal — these
tests exist specifically so the deterministic logic (tools, validation,
scorers) can be verified with zero API calls, and a whole extra framework
isn't needed for that.
"""
import traceback


def run_module(module) -> bool:
    test_fns = [(name, fn) for name, fn in vars(module).items() if name.startswith("test_")]
    print(f"=== {module.__name__} ({len(test_fns)} tests) ===")
    all_passed = True
    for name, fn in test_fns:
        try:
            fn()
            print(f"  PASS  {name}")
        except Exception:
            all_passed = False
            print(f"  FAIL  {name}")
            traceback.print_exc()
    print()
    return all_passed
