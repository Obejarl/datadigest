"""The program's map (datadigest/sections.py) stays complete: every page and every API route has
a section, and every page shows the same navigation."""

import re
from pathlib import Path

import pytest
from fastapi.routing import APIRoute

from datadigest import sections
from datadigest.api.main import app

STATIC = Path(__file__).parent.parent / "datadigest" / "static"
PAGES = {  # a URL of every page, and the navigation link it should light up
    "/": "/",
    "/datasets/x": "/",
    "/optimize": "/optimize",
    "/optimizations/x": "/optimize",
    "/capacity": "/capacity",
    "/account": "/account",
}
OUTSIDE_THE_MAP = {"/login"}  # nothing to navigate to before signing in


def test_every_feature_has_exactly_one_section():
    tags = [tag for s in sections.SECTIONS for tag in s.tags]
    pages = [page.path for s in sections.SECTIONS for page in s.pages]
    assert len(tags) == len(set(tags)) and len(pages) == len(set(pages))
    assert len({s.key for s in sections.SECTIONS}) == len(sections.SECTIONS)
    for s in sections.SECTIONS:
        assert s.question.endswith("?") and s.features and s.pages and s.code
        for where in s.code:
            assert (STATIC.parent.parent / where).exists(), where


def test_every_api_route_belongs_to_a_section():
    known = {tag for s in sections.SECTIONS for tag in s.tags}
    for route in app.routes:
        if isinstance(route, APIRoute) and route.include_in_schema:
            assert route.tags, f"{route.path} has no tag"
            assert set(route.tags) <= known, f"{route.path}: add {route.tags} to a section"
    assert [t["name"] for t in app.openapi()["tags"]] == [t for s in sections.SECTIONS for t in s.tags]


def test_every_page_route_belongs_to_a_section():
    for route in app.routes:
        if isinstance(route, APIRoute) and not route.include_in_schema and route.path not in OUTSIDE_THE_MAP:
            path = re.sub(r"\{[^}]+\}", "", route.path)  # /datasets/{dataset_id} -> /datasets/
            assert sections.section_of(path) is not None, f"{route.path}: add this page to a section"


@pytest.mark.parametrize("url", sorted(PAGES))
def test_pages_share_one_navigation_with_the_current_page_marked(client, url):
    html = client.get(url).text
    nav = re.search(r'<nav class="nav".*?</nav>', html, flags=re.S).group(0)
    links = re.findall(r'<a href="([^"]+)"', nav)
    assert links == [page.path for s in sections.SECTIONS for page in s.pages]
    assert re.findall(r'<a href="([^"]+)" class="active"', nav) == [PAGES[url]]
    assert nav.count('class="nav-group"') == len(sections.SECTIONS)
    assert '<nav class="sitemap"' in html  # the same links for narrow screens
    for placeholder in ("<!--nav-->", "<!--sections-->", "<!--sitemap-->"):
        assert placeholder not in html


def test_pages_do_not_carry_their_own_copy_of_the_navigation():
    for file in STATIC.glob("*.html"):
        assert '<nav class="nav"' not in file.read_text(encoding="utf-8"), file.name


def test_the_home_page_shows_every_section(client):
    html = client.get("/").text
    for s in sections.SECTIONS:
        assert f'data-section="{s.key}"' in html and s.question in html
    assert html.count("You are here") == 1
    assert 'class="section-card" data-section="optimize" href="/optimize"' in html
