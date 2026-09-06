"""Runs unit tests and scenarios and returns JSON results."""

import sys, os, json, io, traceback
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def run_unit_tests():
    """Run all unittest test cases and return structured results."""
    import unittest

    loader = unittest.TestLoader()
    suite = loader.discover(os.path.dirname(os.path.abspath(__file__)), pattern="test_*.py")

    stream = io.StringIO()
    runner = unittest.TextTestRunner(stream=stream, verbosity=2)
    result = runner.run(suite)

    output = stream.getvalue()

    tests = []
    for test_case, trace in result.failures + result.errors:
        tests.append({
            "name": str(test_case),
            "passed": False,
            "detail": trace.splitlines()[-1] if trace else "failure"
        })

    passed_count = result.testsRun - len(result.failures) - len(result.errors)
    tests_passed = [{"name": "passed", "passed": True, "detail": ""} for _ in range(passed_count)]

    return {
        "total": result.testsRun,
        "passed": passed_count,
        "failed": len(result.failures) + len(result.errors),
        "output": output,
        "tests": tests_passed + tests
    }


def run_all_scenarios():
    from tests.scenarios import run_all_scenarios as _run
    return _run()


def run_everything():
    return {
        "tests": run_unit_tests(),
        "scenarios": run_all_scenarios(),
    }


if __name__ == "__main__":
    print(json.dumps(run_everything(), ensure_ascii=False))
