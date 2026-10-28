"""What a person can do in the browser. API-level behavior is covered by tests/; these check the
dashboard code that only a browser runs: rendering, forms, dialogs, tabs, keyboard, layout."""

import pytest
from playwright.sync_api import expect

from tests_e2e.conftest import get, post


def test_home_shows_totals_and_a_sample_runs_end_to_end(page, server):
    page.goto(server + "/")
    expect(page.locator("h1")).to_contain_text("Data quality")
    expect(page.locator("#kpis .tile")).to_have_count(4)
    expect(page.locator("#pills .pill").first).to_contain_text("API ready")

    page.locator("#samples .sample", has_text="tr_survey.csv").click()
    page.wait_for_url("**/datasets/*")
    expect(page.locator("#result")).to_be_visible()
    expect(page.locator("#tiles")).to_contain_text("Quality score")
    expect(page.locator("#title")).to_have_text("tr_survey.csv")
    expect(page.locator("#chips")).to_contain_text("cp1254")  # the Turkish Excel export was detected


def test_uploading_two_files_through_the_file_input(page, server, tmp_path):
    first, second = tmp_path / "alpha.csv", tmp_path / "beta.csv"
    first.write_text("x,y\n1,2\n3,4\n5,6\n", encoding="utf-8")
    second.write_text("name;score\nann;1,5\nbob;2,5\n", encoding="utf-8")
    page.goto(server + "/")
    page.set_input_files("#file", [str(first), str(second)])
    expect(page.locator("#uploads .up")).to_have_count(2)
    expect(page.locator("#uploads .st.ok")).to_have_count(2)  # both uploaded, no redirect for several files
    for name in ("alpha.csv", "beta.csv"):
        row = page.locator("#datasets tr", has_text=name)
        expect(row).to_contain_text("done")


def test_dataset_page_tabs_keyboard_and_warning_jump(page, server, sales_id):
    page.goto(f"{server}/datasets/{sales_id}")
    expect(page.locator("#result")).to_be_visible()
    expect(page.locator("#pane-overview")).to_have_class("pane active")

    page.keyboard.press("4")
    expect(page.locator("#pane-preview")).to_have_class("pane active")
    expect(page.locator("#preview-body tr")).to_have_count(20)
    page.keyboard.press("1")

    page.locator("#warnings .issue.link", has_text="discount_pct").click()
    expect(page.locator("#pane-columns")).to_have_class("pane active")
    expect(page.locator(".col.flash h3")).to_have_text("discount_pct")
    assert page.url.endswith("#columns")  # the tab is a shareable link

    page.locator("#col-sort").select_option("missing")
    expect(page.locator("#cols .col h3").first).to_have_text("discount_pct")
    page.locator(".fchip", has_text="boolean").click()
    expect(page.locator("#cols .col:not([hidden])")).to_have_count(1)


def test_typing_in_a_field_does_not_trigger_shortcuts(page, server, sales_id):
    page.goto(f"{server}/datasets/{sales_id}#columns")
    expect(page.locator("#pane-columns")).to_have_class("pane active")
    page.locator("#col-search").fill("4")  # "4" would open the preview tab outside a field
    expect(page.locator("#pane-columns")).to_have_class("pane active")


def test_delete_asks_first_and_cancel_keeps_the_dataset(page, server, tmp_path):
    victim = tmp_path / "to-delete.csv"
    victim.write_text("a,b\n1,2\n3,4\n", encoding="utf-8")
    page.goto(server + "/")
    page.set_input_files("#file", [str(victim), str(victim)])  # two files: stay on the list page
    row = page.locator("#datasets tr", has_text="to-delete.csv").first
    expect(row).to_contain_text("done")

    row.locator('button[aria-label^="Delete"]').click()
    dialog = page.locator("dialog.modal")
    expect(dialog).to_be_visible()
    expect(dialog).to_contain_text("optimization runs")  # tells you what else goes
    dialog.get_by_role("button", name="Cancel").click()
    expect(dialog).to_have_count(0)
    expect(page.locator("#datasets tr", has_text="to-delete.csv")).to_have_count(2)

    row.locator('button[aria-label^="Delete"]').click()
    page.locator("dialog.modal .solid-danger").click()
    expect(page.locator("#datasets tr", has_text="to-delete.csv")).to_have_count(1)


def test_optimizer_example_one_click_to_a_result_with_charts(page, server):
    page.goto(server + "/optimize")
    expect(page.locator(".kind-card")).to_have_count(4)
    page.locator('.kind-card[data-kind="production"] .btn.primary').click()
    page.wait_for_url("**/optimizations/*")
    expect(page.locator("#result .tile").first).to_contain_text("Total profit")
    expect(page.locator("#result")).to_contain_text("What the optimum tells you")
    expect(page.locator("#chips")).to_contain_text("optimal")
    expect(page.locator("#result .js-plotly-plot").first).to_be_visible()  # Plotly drew a chart


def test_change_inputs_reopens_the_form_with_that_runs_parameters(page, server, production_run_id):
    page.goto(f"{server}/optimizations/{production_run_id}")
    page.locator("#change-inputs").click()
    expect(page.locator("#config")).to_be_visible()
    machine = page.locator("#config-fields .res-row", has_text="machine_hours")
    expect(machine.locator("input[type=number]")).to_have_value("600")
    expect(machine.locator("input[type=checkbox]")).to_be_checked()

    machine.locator("input[type=number]").fill("900")
    page.locator("#config-solve").click()
    page.wait_for_url("**/optimizations/*")
    expect(page.locator("#chips")).to_contain_text("optimal")
    assert page.url.split("/")[-1] != production_run_id  # a new run, the old one is kept


def test_capacity_recomputes_when_the_inputs_change(page, server):
    page.goto(server + "/capacity")
    inputs = page.locator("#cap-form input")
    expect(inputs).to_have_count(6)
    inputs.nth(0).fill("30")  # arrivals per minute
    inputs.nth(1).fill("6")  # service seconds
    inputs.nth(2).fill("2")  # target wait
    # The page recomputes after a short pause and then writes the scenario into the address bar.
    page.wait_for_function("location.search.includes('target_wait_seconds=2')")
    assert "arrival_per_min=30" in page.url and "service_seconds=6" in page.url  # shareable link
    tile = page.locator("#cap-result .tile", has_text="Recommended workers")
    expect(tile.locator(".v")).to_have_text("5")  # 3 busy workers on average, so 5 keep the wait under 2 s
    expect(page.locator("#hpa")).to_contain_text("minReplicas: 5")


@pytest.mark.parametrize("route", ["/", "/optimize", "/capacity"])
def test_phone_width_has_no_horizontal_scroll(browser, server, route):
    context = browser.new_context(viewport={"width": 375, "height": 812})
    page = context.new_page()
    page.goto(server + route)
    page.wait_for_load_state("networkidle")
    widths = page.evaluate("[document.documentElement.scrollWidth, innerWidth]")
    context.close()
    assert widths[0] <= widths[1], f"{route} scrolls sideways: {widths}"


def test_phone_width_dataset_and_result_pages(browser, server, sales_id, production_run_id):
    context = browser.new_context(viewport={"width": 375, "height": 812})
    page = context.new_page()
    for route in (f"/datasets/{sales_id}", f"/optimizations/{production_run_id}"):
        page.goto(server + route)
        page.wait_for_load_state("networkidle")
        widths = page.evaluate("[document.documentElement.scrollWidth, innerWidth]")
        assert widths[0] <= widths[1], f"{route} scrolls sideways: {widths}"
        # charts must have been drawn at phone width, not left at Plotly's 700 px default
        # Charts are drawn lazily, when they scroll into view. Scroll the way a person does: a single
        # jump to the bottom can skip past a chart without it ever being visible.
        page.evaluate(
            "async () => { for (let y = 0; y < document.body.scrollHeight; y += 300) "
            "{ window.scrollTo(0, y); await new Promise(r => setTimeout(r, 80)); } }"
        )
        page.wait_for_selector(".js-plotly-plot", state="attached")
        page.wait_for_timeout(800)
        sizes = page.evaluate(
            "[...document.querySelectorAll('.js-plotly-plot')].map(e => e.getBoundingClientRect().width)"
        )
        assert sizes and max(sizes) <= 375, sizes
    context.close()


def test_reprocess_button_runs_the_analysis_again(page, server, sales_id):
    before = get(server, f"/api/datasets/{sales_id}")["finished_at"]
    page.goto(f"{server}/datasets/{sales_id}")
    page.locator("#rerun").click()
    # The click starts a request; until it lands the old "done" is still there,
    # so wait for a newer finish time.
    for _ in range(40):
        after = get(server, f"/api/datasets/{sales_id}")
        if after["status"] == "done" and after["finished_at"] and after["finished_at"] > before:
            break
        page.wait_for_timeout(500)
    else:
        raise AssertionError(f"the analysis never ran again: {after}")
    expect(page.locator("#result")).to_be_visible()


def test_a_failed_file_offers_try_again(page, server, tmp_path):
    bad = tmp_path / "broken.csv"
    bad.write_text("only_header\n", encoding="utf-8")
    page.goto(server + "/")
    page.set_input_files("#file", str(bad))
    page.wait_for_url("**/datasets/*")
    expect(page.locator("#failed")).to_be_visible()
    expect(page.locator("#error")).to_have_text("File has no data rows")
    expect(page.locator("#retry")).to_be_visible()
    dataset_id = page.url.split("/")[-1]
    assert post(server, f"/api/datasets/{dataset_id}/reprocess")["status"] == "queued"
