"""Run the custom module examples and assert every custom module was called."""

import asyncio
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import examples.custom_modules as mods


def test_custom_modules_every_module_called():
    asyncio.run(mods.main())

    assert mods.TOKENIZER_CALLS, "custom tokenizer was never called"
    assert mods.RENDERER_CALLS, "custom renderer was never called"
    assert mods.EXTRACTOR_CALLS, "custom fact extractor was never called"
    assert mods.SUMMARIZER_CALLS, "custom history summarizer was never called"
    assert mods.PROVIDER_CALLS, "openai_compatible provider was never called"
    assert mods.BACKEND_CALLS, "custom memory backend was never called"
