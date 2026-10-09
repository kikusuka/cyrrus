from cyrrus.data import Slide
from cyrrus.tray import SlideTray


def slide(slide_id: str) -> Slide:
    return Slide(id=slide_id, type="data", content=slide_id, tokens=1, priority=1)


def test_ghost_expires_after_configured_untriggered_turns():
    tray = SlideTray(max_active_turns=1, max_ghost_turns=2)
    coding = slide("coding")
    tray.update([coding])
    tray.update([])
    tray.update([])  # coding fades, at ghost age zero
    assert [s.id for s in tray.ghosts] == ["coding"]

    tray.update([])  # ghost age 1
    assert [s.id for s in tray.ghosts] == ["coding"]

    tray.update([])  # ghost age 2 - should expire
    assert tray.ghosts == []


def test_retriggering_ghost_resurrects_it_as_active():
    tray = SlideTray(max_active_turns=1, max_ghost_turns=2)
    coding = slide("coding")
    tray.update([coding])
    tray.update([])
    tray.update([])
    assert tray.ghosts[0].is_ghost

    tray.update([coding])
    assert [s.id for s in tray.active] == ["coding"]
    assert tray.ghosts == []
    assert tray.turn_counters["coding"] == 0


def test_ghost_slide_cap_remains_a_secondary_limit():
    tray = SlideTray(max_active_turns=1, max_ghost_slides=1, max_ghost_turns=10)
    first = slide("first")
    second = slide("second")
    tray.update([first])
    tray.update([])
    tray.update([second])
    tray.update([])
    tray.update([])

    assert [s.id for s in tray.ghosts] == ["second"]
    assert "first" not in tray.ghost_ages
