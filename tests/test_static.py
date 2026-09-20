"""The favicon and the static mount that serves it.

The icon has to load on the Basic-auth prompt, before the viewer has any
credentials to send, so these assets sit outside the auth gate that covers
every other route. That is deliberate, and worth a test that says so.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from pitch_analyzer import web

STATIC = Path(web.__file__).resolve().parent / "static"
ICONS = ("favicon.ico", "icon.png", "apple-touch-icon.png")


@pytest.fixture
def client(monkeypatch):
    """A password is set, so anything reachable here is genuinely public."""
    monkeypatch.setenv("APP_PASSWORD", "secret")
    monkeypatch.delenv("ALLOW_ANONYMOUS", raising=False)
    with TestClient(web.app) as test_client:
        yield test_client


@pytest.mark.parametrize("name", ICONS)
def test_the_icon_files_are_shipped(name: str) -> None:
    assert (STATIC / name).is_file(), f"{name} missing from the static directory"


def test_the_icons_are_the_images_they_claim_to_be() -> None:
    """A PNG renamed .ico is not an ICO, and browsers that need one will fail."""
    from PIL import Image

    with Image.open(STATIC / "favicon.ico") as ico:
        assert ico.format == "ICO"
        # Multi-resolution, so the mark stays legible in a tab and a bookmark bar.
        assert {(16, 16), (32, 32)} <= set(ico.info["sizes"])

    with Image.open(STATIC / "apple-touch-icon.png") as touch:
        assert touch.format == "PNG"
        assert touch.size == (180, 180)
        # iOS composites transparency onto black, which would swallow the white
        # gaps this mark is drawn with.
        assert touch.mode == "RGB"

    with Image.open(STATIC / "icon.png") as icon:
        assert icon.format == "PNG"
        assert icon.width == icon.height


@pytest.mark.parametrize("name", ICONS)
def test_the_icons_are_served_without_credentials(client, name: str) -> None:
    response = client.get(f"/static/{name}")

    assert response.status_code == 200, "the icon must load on the login prompt"
    assert response.headers["content-type"].startswith("image/")
    assert response.content == (STATIC / name).read_bytes()


def test_the_default_favicon_path_is_served(client) -> None:
    """Browsers request /favicon.ico whatever the HTML declares."""
    response = client.get("/favicon.ico")

    assert response.status_code == 200
    assert response.content == (STATIC / "favicon.ico").read_bytes()


def test_the_static_mount_did_not_open_up_the_rest_of_the_app(client) -> None:
    """Public assets must not have made the pages that spend credits public."""
    assert client.get("/").status_code == 401


def test_the_page_references_the_shipped_icons(client) -> None:
    html = client.get("/", auth=("ten", "secret")).text

    assert '<link rel="icon" href="/static/favicon.ico"' in html
    assert 'href="/static/apple-touch-icon.png"' in html
    # The hand-drawn SVG placeholder is gone, replaced by the real mark.
    assert "data:image/svg+xml" not in html


def test_every_referenced_asset_actually_resolves(client) -> None:
    """A tag pointing at a path that 404s is worse than no tag at all.

    Covers src= as well as href=, so the header logo is checked and not only
    the icons in <head>.
    """
    import re

    html = client.get("/", auth=("ten", "secret")).text
    referenced = set(re.findall(r'(?:href|src)="(/static/[^"]+)"', html))

    assert referenced, "the page declares no static assets"
    for path in sorted(referenced):
        assert client.get(path).status_code == 200, path


def test_the_header_shows_the_real_mark(client) -> None:
    """The header carried a hand-drawn SVG approximation of the logo: three
    arcs and three circles that rendered as scattered blobs rather than the
    ring of three figures the mark actually is."""
    html = client.get("/", auth=("ten", "secret")).text

    assert '<img class="brand-mark" src="/static/icon.png"' in html
    assert "<svg class=\"brand-mark\"" not in html
    # The wordmark beside it supplies the accessible name, so the image is
    # decorative and must not be announced twice.
    assert 'alt="" aria-hidden="true"' in html
    assert "TEN Capital" in html
