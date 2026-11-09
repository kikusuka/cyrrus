import pytest

from cyrrus.config import validate_config
from cyrrus.memory import MemoryVault
from cyrrus.trace import Trace


async def _seed(vault):
    await vault.upsert("s", "fact_a", "alpha beta", 2)
    await vault.upsert("s", "fact_b", "alpha", 1)
    await vault.upsert("s", "fact_c", "beta", 1)


@pytest.mark.asyncio
async def test_relative_floor_keeps_top_and_drops_weak(tmp_path):
    vault = MemoryVault(
        db_path=str(tmp_path / "floor.db"), min_relative_score=0.8
    )
    await _seed(vault)
    trace = Trace(session_id="s")
    slides = await vault.retrieve("s", "alpha beta", limit=5, trace=trace)

    assert [s.id for s in slides] == ["mem_fact_a"]
    candidates = trace.to_dict()["candidates"]
    assert candidates[0]["id"] == "fact_a" and candidates[0]["included"]
    weak = [c for c in candidates if c["id"] in ("fact_b", "fact_c")]
    assert weak and all(not c["included"] for c in weak)
    assert all(
        c["dropped_reason"] == "below_relative_floor" for c in weak
    ), weak


@pytest.mark.asyncio
async def test_sharp_floor_still_keeps_positive_top1(tmp_path):
    vault = MemoryVault(
        db_path=str(tmp_path / "top1.db"), min_relative_score=1.0
    )
    await _seed(vault)
    slides = await vault.retrieve("s", "alpha beta", limit=5)
    assert len(slides) == 1
    assert slides[0].id == "mem_fact_a"


@pytest.mark.asyncio
async def test_pinned_candidate_is_never_dropped(tmp_path):
    vault = MemoryVault(
        db_path=str(tmp_path / "pinned.db"), min_relative_score=0.8
    )
    await _seed(vault)
    trace = Trace(session_id="s")
    slides = await vault.retrieve(
        "s", "alpha beta", limit=5, trace=trace, pinned_keys={"fact_c"}
    )

    assert {"mem_fact_a", "mem_fact_c"} <= {s.id for s in slides}
    pinned = [c for c in trace.to_dict()["candidates"] if c["id"] == "fact_c"][0]
    assert pinned["included"] and pinned["reason"] == "pinned"


def test_config_accepts_min_relative_score():
    cfg = validate_config({"memory": {"min_relative_score": 0.55}})
    assert cfg["memory"]["min_relative_score"] == 0.55
    with pytest.raises(ValueError):
        validate_config({"memory": {"min_relative_score": 1.5}})
