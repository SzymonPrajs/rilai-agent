"""Automated test script for synthesizer prompt fixes.

Tests that the system produces substantive responses, not cop-outs.
"""

import asyncio
import re
import sys
from dataclasses import dataclass
from pathlib import Path

# Add src to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from rilai.core.engine import Engine


@dataclass
class TestResult:
    """Result of a single prompt test."""

    prompt: str
    response: str
    passed: bool
    failures: list[str]


# Cop-out phrases that indicate the system failed to produce a real response
COP_OUT_PHRASES = [
    "i'm not sure how to answer",
    "unable to formulate",
    "i don't have a clear response",
    "i'm having trouble",
    "i can't formulate",
    "i'm not quite sure",
    "i don't know how to respond",
    "not able to formulate",
    "i'm not sure i can",
    "i'm not sure that i",
    "i can't pin down",
    "not sure i can pin down",
]

# Test prompts covering different categories
TEST_PROMPTS = [
    # Simple factual
    "What's the capital of France?",
    # Opinion
    "What is the most interesting thing about pizza?",
    # Creative
    "Tell me a joke",
    # Emotional
    "How are you feeling today?",
    # Technical
    "Explain recursion briefly",
    # Greeting
    "Hello, how are you?",
    # Request
    "Give me three fun facts about cats",
    # Simple question
    "What color is the sky?",
]


def validate_response(prompt: str, response: str) -> TestResult:
    """Validate that a response is substantive, not a cop-out."""
    failures = []

    # Check not empty
    if not response or not response.strip():
        failures.append("Response is empty")

    # Check minimum length
    if len(response.strip()) < 20:
        failures.append(f"Response too short ({len(response.strip())} chars < 20)")

    # Check for cop-out phrases
    response_lower = response.lower()
    for phrase in COP_OUT_PHRASES:
        if phrase in response_lower:
            failures.append(f"Contains cop-out phrase: '{phrase}'")
            break

    return TestResult(
        prompt=prompt,
        response=response,
        passed=len(failures) == 0,
        failures=failures,
    )


async def run_test(engine: Engine, prompt: str) -> TestResult:
    """Run a single test prompt through the engine."""
    try:
        response = await engine.process_message(prompt)
        return validate_response(prompt, response)
    except Exception as e:
        return TestResult(
            prompt=prompt,
            response="",
            passed=False,
            failures=[f"Exception: {e}"],
        )


async def run_all_tests() -> list[TestResult]:
    """Run all test prompts and return results."""
    print("=" * 60)
    print("SYNTHESIZER PROMPT TEST SUITE")
    print("=" * 60)
    print()

    # Initialize engine
    print("Initializing engine...")
    engine = Engine()
    await engine.start()

    results = []

    for i, prompt in enumerate(TEST_PROMPTS, 1):
        print(f"\n[{i}/{len(TEST_PROMPTS)}] Testing: {prompt[:50]}...")

        result = await run_test(engine, prompt)
        results.append(result)

        if result.passed:
            print(f"  ✓ PASSED")
            print(f"  Response: {result.response[:100]}...")
        else:
            print(f"  ✗ FAILED")
            for failure in result.failures:
                print(f"    - {failure}")
            if result.response:
                print(f"  Response: {result.response[:100]}...")

    # Stop engine
    await engine.stop()

    return results


def print_summary(results: list[TestResult]) -> bool:
    """Print test summary and return True if all passed."""
    print()
    print("=" * 60)
    print("SUMMARY")
    print("=" * 60)

    passed = sum(1 for r in results if r.passed)
    failed = sum(1 for r in results if not r.passed)

    print(f"Passed: {passed}/{len(results)}")
    print(f"Failed: {failed}/{len(results)}")

    if failed > 0:
        print()
        print("FAILED PROMPTS:")
        for r in results:
            if not r.passed:
                print(f"  - {r.prompt}")
                for f in r.failures:
                    print(f"      {f}")

    return failed == 0


async def main():
    """Main entry point."""
    results = await run_all_tests()
    all_passed = print_summary(results)

    sys.exit(0 if all_passed else 1)


if __name__ == "__main__":
    asyncio.run(main())
