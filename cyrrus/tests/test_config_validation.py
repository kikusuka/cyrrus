"""
Tests for config_validation.py - and for the fact that Projector
actually calls it at construction time, not just that the function
exists in isolation.
"""
import asyncio
import json
import os
import sys
from cyrrus.config_validation import validate_config, ConfigError
from cyrrus import Projector

FAILED = []


def check(name, condition):
    status = "PASS" if condition else "FAIL"
    print(f"[{status}] {name}")
    if not condition:
        FAILED.append(name)


def raises_config_error(config) -> bool:
    try:
        validate_config(config)
        return False
    except ConfigError:
        return True


def test_valid_config_passes():
    config = {
        "core_lamp": {"content": "You are helpful.", "tokens": 10, "priority": 1000},
        "web_search": {"type": "tool", "content": "x", "tokens": 10, "priority": 500,
                        "handler": "search", "triggers": ["search"]},
    }
    try:
        validate_config(config)
        check("a well-formed config passes validation without raising", True)
    except ConfigError as e:
        check(f"a well-formed config passes validation without raising (raised: {e})", False)


def test_missing_core_lamp():
    config = {"web_search": {"type": "tool", "content": "x", "tokens": 10, "priority": 500}}
    check("missing core_lamp is rejected", raises_config_error(config))


def test_missing_required_field():
    # Only 'content' is required now. tokens and priority have defaults.
    config = {"core_lamp": {"tokens": 10, "priority": 1000},
               "bad_slide": {"tokens": 10}}  # missing content - the only truly required field
    check("a slide missing content is rejected", raises_config_error(config))


def test_wrong_field_type():
    config = {"core_lamp": {"content": "x", "tokens": "not a number", "priority": 1000}}
    check("wrong type for a required field is rejected", raises_config_error(config))


def test_tool_without_handler():
    config = {"core_lamp": {"content": "x", "tokens": 10, "priority": 1000},
               "web_search": {"type": "tool", "content": "x", "tokens": 10, "priority": 500}}
    check("a tool-type slide with no handler is rejected", raises_config_error(config))


def test_handler_without_tool_type():
    config = {"core_lamp": {"content": "x", "tokens": 10, "priority": 1000},
               "odd_slide": {"type": "lens", "content": "x", "tokens": 10, "priority": 500,
                              "handler": "something"}}
    check("a handler set on a non-tool slide is rejected", raises_config_error(config))


def test_bad_triggers_type():
    config = {"core_lamp": {"content": "x", "tokens": 10, "priority": 1000},
               "odd_slide": {"content": "x", "tokens": 10, "priority": 500,
                              "triggers": "search"}}  # should be a list, not a string
    check("triggers as a string instead of a list of strings is rejected", raises_config_error(config))


def test_not_a_dict():
    check("a non-dict config is rejected", raises_config_error(["not", "a", "dict"]))


def test_empty_config():
    check("an empty config is rejected", raises_config_error({}))


async def test_projector_actually_validates_on_construction():
    bad_config = {"web_search": {"type": "tool", "content": "x", "tokens": 10, "priority": 500}}

    async def mock_llm(messages):
        return "x"

    raised = False
    try:
        Projector(bad_config, llm_call=mock_llm)
    except ConfigError:
        raised = True
    check("Projector itself raises ConfigError for a bad config, not just the standalone function",
          raised)


async def test_projector_still_works_with_real_config():
    config_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "slides.json")
    with open(config_path) as f:
        real_config = json.load(f)

    async def mock_llm(messages):
        return "x"

    try:
        p = Projector(real_config, llm_call=mock_llm)
        check("the project's own real slides.json still passes validation", True)
    except ConfigError as e:
        check(f"the project's own real slides.json still passes validation (raised: {e})", False)


async def main():
    test_valid_config_passes()
    test_missing_core_lamp()
    test_missing_required_field()
    test_wrong_field_type()
    test_tool_without_handler()
    test_handler_without_tool_type()
    test_bad_triggers_type()
    test_not_a_dict()
    test_empty_config()
    await test_projector_actually_validates_on_construction()
    await test_projector_still_works_with_real_config()

    print()
    if FAILED:
        print(f"{len(FAILED)} FAILED: {FAILED}")
        sys.exit(1)
    else:
        print("ALL CONFIG VALIDATION TESTS PASSED")


if __name__ == "__main__":
    asyncio.run(main())
