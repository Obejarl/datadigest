"""The sign-in flow in a browser, against a server started with ACCESS_TOKEN."""

from playwright.sync_api import expect

from tests_e2e.conftest import TOKEN


def test_pages_send_you_to_the_login_and_back_again_after_signing_in(page, secured_server):
    page.goto(secured_server + "/optimize")
    page.wait_for_url("**/login?next=/optimize")
    expect(page.locator("h1")).to_have_text("Sign in")

    page.fill("#token", "not-the-token")
    page.click("#login-submit")
    expect(page.locator("#login-error")).to_contain_text("not correct")
    assert "/login" in page.url

    page.fill("#token", TOKEN)
    page.click("#login-submit")
    page.wait_for_url("**/optimize")
    expect(page.locator(".kind-card")).to_have_count(4)  # the real page, not the login form


def test_sign_out_returns_to_the_login(page, secured_server):
    page.goto(secured_server + "/login")
    page.fill("#token", TOKEN)
    page.click("#login-submit")
    page.wait_for_url(secured_server + "/")
    page.locator("button.signout").click()
    page.wait_for_url("**/login")
    page.goto(secured_server + "/")
    page.wait_for_url("**/login?next=/")


def test_the_next_parameter_cannot_send_you_to_another_site(page, secured_server):
    for hostile in ("//example.org/phish", "/\\example.org/phish", "https://example.org/"):
        page.context.clear_cookies()
        page.goto(f"{secured_server}/login?next={hostile}")
        page.fill("#token", TOKEN)
        page.click("#login-submit")
        page.wait_for_load_state("networkidle")
        assert page.url.startswith(secured_server), f"left the site for next={hostile}: {page.url}"
        assert "example.org" not in page.url


def test_api_calls_without_a_session_are_refused(secured_server):
    import urllib.error
    import urllib.request

    try:
        urllib.request.urlopen(secured_server + "/api/datasets", timeout=5)
        raise AssertionError("the API answered without a token")
    except urllib.error.HTTPError as err:
        assert err.code == 401
