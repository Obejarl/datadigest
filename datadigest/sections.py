"""The map of the program: which features there are and which section each belongs to.

DataDigest does more than one thing, on purpose. What keeps that manageable is that every
feature has one home, and that the home is written down once, here. The navigation bar, the
section cards on the home page and the grouping of the API reference are all generated from
this file, and a test fails when a page or an API route is added without giving it a section.

    Data quality   is this file trustworthy?        upload, profile, statistics, report
    Optimize       what should we do with it?       planning models solved on the same files
    Operations     how do we run DataDigest itself?  capacity, accounts, health, API reference

To add a feature: put its page and its API tag in the section it belongs to (or add a section).
Nothing else needs to know.
"""

from __future__ import annotations

from dataclasses import dataclass
from html import escape


@dataclass(frozen=True)
class Page:
    path: str  # where the navigation link goes
    label: str
    # Other pages that light this link up (a dataset's page belongs to the dataset list).
    also: tuple[str, ...] = ()


@dataclass(frozen=True)
class Section:
    key: str
    title: str
    question: str  # the one question this section answers
    summary: str
    features: tuple[str, ...]
    pages: tuple[Page, ...]
    tags: tuple[str, ...]  # OpenAPI tags of the routes that belong here
    code: tuple[str, ...]  # where its logic lives

    @property
    def home(self) -> str:
        return self.pages[0].path


SECTIONS: tuple[Section, ...] = (
    Section(
        key="data",
        title="Data quality",
        question="Can this file be trusted?",
        summary="Upload a CSV and get a quality score, the problems behind it, statistics in plain "
        "words and a report to share.",
        features=(
            "Quality score and warnings",
            "Column profiles and correlations",
            "Statistics in plain words",
            "Big files with Spark",
            "Shareable HTML report",
        ),
        pages=(Page("/", "Datasets", also=("/datasets/",)),),
        tags=("datasets", "stats", "samples", "server files"),
        code=("datadigest/core/", "datadigest/serverfiles.py"),
    ),
    Section(
        key="optimize",
        title="Optimize",
        question="What should we do with it?",
        summary="Production plans, shipping routes, team assignments and budgets, solved to the "
        "proven optimum on your datasets.",
        features=(
            "Production planning",
            "Transportation",
            "Assignment",
            "Budget allocation",
            "Comparison with the rule of thumb",
        ),
        pages=(Page("/optimize", "Optimize", also=("/optimizations/",)),),
        tags=("optimize",),
        code=("datadigest/optimize/",),
    ),
    Section(
        key="operations",
        title="Operations",
        question="How do we run DataDigest itself?",
        summary="Size the worker pool from measured load, manage who can sign in, and reach the "
        "API reference.",
        features=(
            "Capacity planning (M/M/c)",
            "Accounts and API tokens",
            "Health checks and metrics",
            "API reference",
        ),
        pages=(
            Page("/capacity", "Capacity"),
            Page("/account", "Account"),
            Page("/docs", "API docs"),
        ),
        tags=("capacity", "accounts", "auth", "health"),
        code=("datadigest/capacity.py", "datadigest/accounts.py", "datadigest/worker.py"),
    ),
)

BY_KEY = {s.key: s for s in SECTIONS}


def section_of(path: str) -> Section | None:
    """The section a page belongs to, or None for pages outside the map (the sign-in page)."""
    for section in SECTIONS:
        for page in section.pages:
            if path == page.path or any(path.startswith(prefix) for prefix in page.also):
                return section
    return None


def _active(page: Page, path: str) -> bool:
    return path == page.path or any(path.startswith(prefix) for prefix in page.also)


def nav_html(path: str) -> str:
    """The navigation bar: one group of links per section, the current page marked."""
    groups = []
    for section in SECTIONS:
        links = "".join(
            '<a href="{href}"{cls}{current}>{label}</a>'.format(
                href=escape(page.path),
                cls=' class="active"' if _active(page, path) else "",
                current=' aria-current="page"' if _active(page, path) else "",
                label=escape(page.label),
            )
            for page in section.pages
        )
        groups.append(
            f'<span class="nav-group" data-section="{section.key}" role="group" '
            f'aria-label="{escape(section.title)}">{links}</span>'
        )
    return '<nav class="nav" aria-label="Sections">' + "".join(groups) + "</nav>"


ICONS = {
    "data": '<path d="M4 6c0-1.7 3.6-3 8-3s8 1.3 8 3-3.6 3-8 3-8-1.3-8-3z"/>'
    '<path d="M4 6v6c0 1.7 3.6 3 8 3s8-1.3 8-3V6M4 12v6c0 1.7 3.6 3 8 3s8-1.3 8-3v-6"/>',
    "optimize": '<path d="m3 17 6-6 4 4 8-8"/><path d="M15 7h6v6"/>',
    "operations": '<path d="M4 20V10M10 20V4M16 20v-8M22 20H2"/>',
}


def cards_html(current: str) -> str:
    """The section cards on the home page: what is under this roof, and where each part lives."""
    cards = []
    for section in SECTIONS:
        here = section.key == current
        features = "".join(f"<li>{escape(f)}</li>" for f in section.features)
        action = (
            '<span class="here">You are here</span>'
            if here
            else f'<span class="btn">Open {escape(section.title)} →</span>'
        )
        tag, href = ("div", "") if here else ("a", f' href="{escape(section.home)}"')
        cards.append(
            f'<{tag} class="section-card{" current" if here else ""}" data-section="{section.key}"{href}>'
            f'<span class="ico"><svg width="21" height="21" viewBox="0 0 24 24" fill="none" '
            f'stroke="currentColor" stroke-width="2" '
            f'stroke-linecap="round" stroke-linejoin="round">{ICONS[section.key]}</svg></span>'
            f'<span class="q">{escape(section.question)}</span>'
            f"<strong>{escape(section.title)}</strong>"
            f'<span class="muted">{escape(section.summary)}</span>'
            f"<ul>{features}</ul>{action}</{tag}>"
        )
    return '<section class="sections" aria-label="What DataDigest does">' + "".join(cards) + "</section>"


def sitemap_html(path: str) -> str:
    """The same links again in the footer: narrow screens hide the bar at the top."""
    groups = []
    for section in SECTIONS:
        links = " · ".join(
            f'<a href="{escape(page.path)}"{' aria-current="page"' if _active(page, path) else ""}>'
            f"{escape(page.label)}</a>"
            for page in section.pages
        )
        groups.append(f"<span><b>{escape(section.title)}</b> {links}</span>")
    return '<nav class="sitemap" aria-label="All sections">' + "".join(groups) + "</nav>"


def openapi_tags() -> list[dict]:
    """Tags in section order, each described by its section, so /docs reads section by section."""
    return [
        {"name": tag, "description": f"**{section.title}** · {section.question}"}
        for section in SECTIONS
        for tag in section.tags
    ]


# Runs before the first paint, so the page transition (style.css) knows which way it is going:
# the page we came from left the direction in sessionStorage (fx.js).
DIRECTION_SCRIPT = (
    "<script>try{document.documentElement.dataset.dir=sessionStorage.getItem('dd-dir')||'';"
    "sessionStorage.removeItem('dd-dir')}catch(e){}</script>"
)


def render(html: str, path: str) -> str:
    """Fill a page's placeholders. Pages stay plain HTML files; only the shared parts are injected."""
    section = section_of(path)
    return (
        html.replace("<!--nav-->", nav_html(path))
        .replace("<!--sections-->", cards_html(section.key if section else ""))
        .replace("<!--sitemap-->", sitemap_html(path))
        .replace("</head>", DIRECTION_SCRIPT + "\n</head>", 1)
    )
