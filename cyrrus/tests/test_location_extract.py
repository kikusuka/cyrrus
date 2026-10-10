import pytest
from cyrrus.extractor import extract_facts


@pytest.mark.asyncio
async def test_location_extract_paris():
    """extract_facts from "I live in Paris" yields a location-related fact."""
    facts = await extract_facts("I live in Paris")
    found_location = False
    for kw, val in facts.items():
        if "location" in kw.lower() or "paris" in val.lower() or "live" in kw.lower():
            found_location = True
    assert found_location, f"Expected location/Paris fact, got: {facts}"


@pytest.mark.asyncio
async def test_location_extract_lisbon():
    """extract_facts from "I moved to Lisbon" yields a location-related fact."""
    facts = await extract_facts("I moved to Lisbon")
    found = False
    for kw, val in facts.items():
        if "lisbon" in val.lower() or "move" in kw.lower() or "location" in kw.lower():
            found = True
    assert found, f"Expected Lisbon/move fact, got: {facts}"
