"""Dashboard smoke flows driven through a real browser.

Five flows, each a regression guard for the refactor work that follows:

1. open the dashboard at ``/``,
2. expand an item card,
3. add a step through the ``/add-step`` endpoint via the UI,
4. open the config modal,
5. open the terminal pane.

Each test starts a fresh condash process against a throwaway conception
tree (see ``conftest.CondashServer``) so mutations never leak.
"""

from __future__ import annotations

from playwright.sync_api import Page, expect

from .conftest import CondashServer

SEED_SLUG = "2026-01-01-e2e-demo"


def test_dashboard_loads(condash_server: CondashServer, page: Page) -> None:
    page.goto(condash_server.url + "/")
    expect(page).to_have_title("Conception Dashboard")
    # The seed project should render as a card in the Projects tab.
    expect(page.locator(f'[id="{SEED_SLUG}"]')).to_be_visible()


def test_open_item_card(condash_server: CondashServer, page: Page) -> None:
    page.goto(condash_server.url + "/")
    card = page.locator(f'[id="{SEED_SLUG}"]')
    expect(card).to_have_class("card collapsed")
    card.locator(".card-header-left").click()
    # Expanding flips the `collapsed` modifier off and reveals the body.
    expect(card).not_to_have_class("card collapsed")
    expect(card.locator(".card-body")).to_be_visible()


def test_add_step(condash_server: CondashServer, page: Page) -> None:
    page.goto(condash_server.url + "/")
    card = page.locator(f'[id="{SEED_SLUG}"]')
    card.locator(".card-header-left").click()
    add_input = card.locator(".add-row input[type=text]").first
    add_input.fill("brand new step from playwright")
    add_input.press("Enter")
    new_step = card.locator(".step .text", has_text="brand new step from playwright")
    expect(new_step).to_be_visible(timeout=5000)
    # Disk-side confirmation: the README now has two checkboxes.
    readme = (
        condash_server.conception_path
        / "projects"
        / "2026-01"
        / "2026-01-01-e2e-demo"
        / "README.md"
    ).read_text(encoding="utf-8")
    assert "- [ ] brand new step from playwright" in readme
    assert readme.count("- [ ] ") == 2  # seed + new


def test_open_config_modal(condash_server: CondashServer, page: Page) -> None:
    page.goto(condash_server.url + "/")
    modal = page.locator("#config-modal")
    # Hidden at load — display:none from CSS + JS.
    expect(modal).to_be_hidden()
    page.locator("button.config-toggle").click()
    expect(modal).to_be_visible(timeout=5000)


def test_open_terminal(condash_server: CondashServer, page: Page) -> None:
    page.goto(condash_server.url + "/")
    term_pane = page.locator("#term-pane")
    # Hidden attribute on first paint.
    expect(term_pane).to_be_hidden()
    page.locator("#term-btn").click()
    expect(term_pane).to_be_visible(timeout=5000)
