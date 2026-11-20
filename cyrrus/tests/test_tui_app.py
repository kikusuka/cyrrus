"""The runnable Textual app: entry point, intro skip, Home, and clean quit."""
from __future__ import annotations

import asyncio
import json

from textual.widgets import Input, TabbedContent

from cyrrus.demo_fixture import build_demo_db
from cyrrus.tui import app as app_module
from cyrrus.tui import widgets


def make_app(tmp_path):
    db_path = build_demo_db(tmp_path / "demo.db")
    return app_module.CyrrusApp(
        demo=True,
        db_path=db_path,
        config_path=tmp_path / "cyrrus.config.json",
    )


async def settle(pilot, app):
    await pilot.pause()
    await app.workers.wait_for_complete()
    await pilot.pause()


async def open_session(pilot, app):
    await settle(pilot, app)
    await pilot.press("x")  # any key skips the intro
    await settle(pilot, app)
    await pilot.press("enter")
    await settle(pilot, app)


def test_run_ui_is_exported():
    assert callable(app_module.run_ui)


def test_run_ui_runs_the_app_and_returns_its_exit_code(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(
        app_module.CyrrusApp,
        "run",
        lambda self: (calls.append(self), 0)[1],
    )

    code = app_module.run_ui(
        ["--demo", "--no-intro", "--db", str(tmp_path / "demo.db")]
    )

    assert code == 0
    assert len(calls) == 1
    assert calls[0].demo is True
    assert calls[0].show_intro is False


def test_demo_ui_boots_home_skips_intro_and_quits(tmp_path):
    app = make_app(tmp_path)

    async def scenario():
        async with app.run_test(size=(100, 30)) as pilot:
            await settle(pilot, app)
            await pilot.press("x")  # any key skips the intro
            await settle(pilot, app)

            assert app.query_one("#views").current == "home-view"
            table = app.query_one("#sessions-table")
            assert table.row_count == 3
            ids = {table.get_row_at(index)[0] for index in range(3)}
            assert ids == {"work", "personal", "scratch"}
            assert "3 sessions" in str(app.query_one("#home-summary").content)

            await pilot.press("q")
            await pilot.pause()

    asyncio.run(scenario())


def test_number_keys_switch_all_session_tabs_and_question_mark_helps(tmp_path):
    app = make_app(tmp_path)

    async def scenario():
        async with app.run_test(size=(100, 30)) as pilot:
            await open_session(pilot, app)
            tabs = app.query_one("#session-tabs", TabbedContent)
            assert tabs.active == "tab-overview"

            for key, tab_id in (
                ("2", "tab-facts"),
                ("3", "tab-trace"),
                ("4", "tab-history"),
                ("5", "tab-settings"),
                ("1", "tab-overview"),
            ):
                await pilot.press(key)
                await pilot.pause()
                assert tabs.active == tab_id, key

            await pilot.press("question_mark")
            await pilot.pause()
            assert isinstance(app.screen, widgets.HelpOverlay)
            await pilot.press("escape")
            await pilot.pause()
            assert not isinstance(app.screen, widgets.HelpOverlay)

            await pilot.press("q")
            await pilot.pause()

    asyncio.run(scenario())


def test_facts_search_filters_and_empty_state(tmp_path):
    app = make_app(tmp_path)

    async def scenario():
        async with app.run_test(size=(100, 30)) as pilot:
            await open_session(pilot, app)
            await pilot.press("/")
            await pilot.pause()
            search = app.query_one("#facts-search", Input)
            assert search.display is True
            assert app.focused is search

            await pilot.press(*"grocery")
            await pilot.press("enter")
            await settle(pilot, app)
            table = app.query_one("#facts-table")
            assert table.row_count == 1
            assert "grocery" in str(table.get_row_at(0))

            search = app.query_one("#facts-search", Input)
            search.value = ""
            search.focus()
            await pilot.press(*"zzzz-not-there")
            await pilot.press("enter")
            await settle(pilot, app)
            assert table.row_count == 0
            assert "No facts match" in str(
                app.query_one("#facts-empty").content
            )

            await pilot.press("q")
            await pilot.pause()

    asyncio.run(scenario())


def test_add_fact_with_n_and_form(tmp_path):
    app = make_app(tmp_path)

    async def scenario():
        async with app.run_test(size=(100, 30)) as pilot:
            await open_session(pilot, app)
            await pilot.press("n")
            await pilot.pause()
            assert isinstance(app.screen, widgets.FormDialog)
            await pilot.press(*"snack")
            await pilot.press("enter")
            await pilot.press(*"pretzels")
            await pilot.press("enter")
            await settle(pilot, app)

            assert not isinstance(app.screen, widgets.FormDialog)
            facts = app.service.facts("personal")
            assert any(fact.key == "snack" for fact in facts)
            table = app.query_one("#facts-table")
            keys = {table.get_row_at(index)[0] for index in range(table.row_count)}
            assert "snack" in keys

            await pilot.press("q")
            await pilot.pause()

    asyncio.run(scenario())


def test_delete_forgets_one_fact_only_after_confirm(tmp_path):
    app = make_app(tmp_path)

    async def scenario():
        async with app.run_test(size=(100, 30)) as pilot:
            await open_session(pilot, app)
            await pilot.press("2")
            await settle(pilot, app)
            table = app.query_one("#facts-table")
            before = table.row_count
            victim = str(table.get_row_at(0)[0])
            assert victim in {fact.key for fact in app.service.facts("personal")}

            await pilot.press("delete")
            await pilot.pause()
            assert isinstance(app.screen, widgets.ConfirmDialog)
            await pilot.press("escape")
            await pilot.pause()
            assert victim in {fact.key for fact in app.service.facts("personal")}

            await pilot.press("delete")
            await pilot.pause()
            assert isinstance(app.screen, widgets.ConfirmDialog)
            await pilot.click("#confirm")
            await settle(pilot, app)

            assert victim not in {fact.key for fact in app.service.facts("personal")}
            assert table.row_count == before - 1

            await pilot.press("q")
            await pilot.pause()

    asyncio.run(scenario())


def test_export_writes_session_facts_json(tmp_path):
    app = make_app(tmp_path)
    app.service.export_dir = tmp_path

    async def scenario():
        async with app.run_test(size=(100, 30)) as pilot:
            await open_session(pilot, app)
            await pilot.press("e")
            await settle(pilot, app)

            path = tmp_path / "cyrrus-personal-facts.json"
            assert path.exists()
            exported = json.loads(path.read_text(encoding="utf-8"))
            assert isinstance(exported, list)
            assert len(exported) == 3
            assert {fact["key"] for fact in exported} >= {"grocery list"}

            await pilot.press("q")
            await pilot.pause()

    asyncio.run(scenario())


def test_settings_edits_valid_value_and_rejects_invalid(tmp_path):
    app = make_app(tmp_path)
    config_path = tmp_path / "cyrrus.config.json"

    async def scenario():
        async with app.run_test(size=(100, 30)) as pilot:
            await open_session(pilot, app)
            await pilot.press("5")
            await pilot.pause()
            assert app.query_one("#session-tabs", TabbedContent).active == "tab-settings"

            await pilot.press("s")
            await pilot.pause()
            dialog = app.screen
            assert isinstance(dialog, widgets.FormDialog)
            field = dialog.query_one("#field-value", Input)
            field.value = "0.75"
            await pilot.press("enter")
            await settle(pilot, app)

            assert not isinstance(app.screen, widgets.FormDialog)
            saved = json.loads(config_path.read_text(encoding="utf-8"))
            assert saved["memory"]["min_relative_score"] == 0.75
            assert "0.75" in str(app.query_one("#settings-body").content)

            await pilot.press("s")
            await pilot.pause()
            dialog = app.screen
            assert isinstance(dialog, widgets.FormDialog)
            field = dialog.query_one("#field-value", Input)
            field.value = "1.5"
            await pilot.press("enter")
            await settle(pilot, app)

            assert isinstance(app.screen, widgets.FormDialog)
            error = str(dialog.query_one("#form-error").content)
            assert "between 0 and 1" in error
            unchanged = json.loads(config_path.read_text(encoding="utf-8"))
            assert unchanged["memory"]["min_relative_score"] == 0.75
            await pilot.press("escape")
            await pilot.pause()

            await pilot.press("q")
            await pilot.pause()

    asyncio.run(scenario())
