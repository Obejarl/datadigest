"""Accounts in a browser: sign in with an email, manage users, and see only your own datasets."""

from playwright.sync_api import expect

from tests_e2e.conftest import ADMIN

MEMBER = ("member@example.org", "e2e-member-password")


def sign_in(page, base, who):
    page.context.clear_cookies()
    page.goto(base + "/login")
    expect(page.locator("#account-fields")).to_be_visible()
    expect(page.locator("#token-fields")).to_be_hidden()  # this server uses accounts, not one token
    page.fill("#email", who[0])
    page.fill("#password", who[1])
    page.click("#login-submit")
    page.wait_for_url(base + "/")
    expect(page.locator("a.pill.who")).to_have_text(who[0])


def test_wrong_password_is_refused_with_a_message(page, accounts_server):
    page.goto(accounts_server + "/account")
    page.wait_for_url("**/login?next=/account")
    page.fill("#email", ADMIN[0])
    page.fill("#password", "not-the-password")
    page.click("#login-submit")
    expect(page.locator("#login-error")).to_contain_text("do not match")
    assert "/login" in page.url


def test_administrator_adds_a_member_who_sees_only_their_own_datasets(page, accounts_server):
    sign_in(page, accounts_server, ADMIN)
    page.locator("#samples .sample", has_text="sales.csv").click()
    page.wait_for_url("**/datasets/*")
    expect(page.locator("#result")).to_be_visible()
    admin_dataset = page.url

    page.locator("a.pill.who").click()
    page.wait_for_url("**/account")
    expect(page.locator("#users tr")).to_have_count(1)
    page.fill("#user-email", MEMBER[0])
    page.fill("#user-password", "short")
    page.locator("#user-form button[type=submit]").click()
    assert page.locator("#user-password").evaluate("el => el.validity.tooShort")  # stopped by the form
    page.fill("#user-password", MEMBER[1])
    page.locator("#user-form button[type=submit]").click()
    row = page.locator("#users tr", has_text=MEMBER[0])
    expect(row).to_contain_text("member")
    expect(row).to_contain_text("active")
    expect(page.locator("#users-count")).to_have_text("2 users")

    sign_in(page, accounts_server, MEMBER)
    expect(page.locator("#datasets td.empty")).to_contain_text("No datasets yet")  # not the administrator's
    page.goto(admin_dataset)
    expect(page.locator("#title")).to_have_text("Dataset not found")
    page.js_errors.clear()  # the page reports the 404 it was meant to get

    page.goto(accounts_server + "/account")
    expect(page.locator("#me-email")).to_have_text(MEMBER[0])
    expect(page.locator("#users-card")).to_be_hidden()  # members do not manage users
    page.click("#token-create")
    expect(page.locator("#token-value")).to_contain_text("dd_")
    expect(page.locator("#me-chips")).to_contain_text("API token set")


def test_a_disabled_member_is_signed_out(page, browser, accounts_server):
    other = browser.new_context()
    member = other.new_page()
    sign_in(page, accounts_server, ADMIN)
    page.goto(accounts_server + "/account")
    page.fill("#user-email", "temp@example.org")
    page.fill("#user-password", "e2e-temp-password")
    page.locator("#user-form button[type=submit]").click()
    row = page.locator("#users tr", has_text="temp@example.org")
    expect(row).to_be_visible()

    sign_in(member, accounts_server, ("temp@example.org", "e2e-temp-password"))
    row.get_by_role("button", name="Disable").click()
    expect(row).to_contain_text("disabled")
    member.goto(accounts_server + "/")
    member.wait_for_url("**/login?next=/")  # the session stopped working at once
    other.close()
