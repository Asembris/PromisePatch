"""The browser bundle the deployed image serves, and the paths it must never answer for.

A single-page application is served by answering anything with ``index.html``, which is exactly
why it is dangerous to mount carelessly: the same rule that makes a deep link work turns every
mistyped API path into an HTML document with status 200. So most of what is asserted here is
what the page is *not* allowed to answer.

Nothing in this file needs a database. The bundle is a directory of files, and these build one.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from starlette.testclient import TestClient

from promisepatch.api.spa import IMMUTABLE, NEVER_STORED
from promisepatch.config import Settings
from promisepatch.main import create_app

INDEX_HTML = (
    '<!doctype html><html><body><div id="root"></div>'
    '<script src="/assets/app-abc123.js"></script></body></html>'
)
BUNDLE_JS = "console.log('the real bundle')"


@pytest.fixture
def bundle(tmp_path: Path) -> Path:
    """A directory shaped exactly like a Vite build: an index, and hashed assets beside it."""
    root = tmp_path / "frontend"
    (root / "assets").mkdir(parents=True)
    (root / "index.html").write_text(INDEX_HTML, encoding="utf-8")
    (root / "assets" / "app-abc123.js").write_text(BUNDLE_JS, encoding="utf-8")
    (root / "favicon.svg").write_text("<svg/>", encoding="utf-8")
    (tmp_path / "outside-the-bundle.txt").write_text("not yours", encoding="utf-8")
    return root


@pytest.fixture
def served(bundle: Path) -> TestClient:
    return TestClient(create_app(Settings(static_root=bundle)))


# ----------------------------------------------------------------- what the page is served for


def test_the_root_serves_the_page(served: TestClient) -> None:
    answer = served.get("/")
    assert answer.status_code == 200
    assert answer.text == INDEX_HTML


def test_a_deep_link_to_a_case_serves_the_page(served: TestClient) -> None:
    """`?case=<id>` is the whole reload guarantee, and it has to survive a cold request."""
    answer = served.get("/?case=0198f0a0-0000-7000-8000-000000000001")
    assert answer.status_code == 200
    assert answer.text == INDEX_HTML


def test_an_unknown_path_serves_the_page_rather_than_a_404(served: TestClient) -> None:
    """A route inside the page is not a missing document."""
    answer = served.get("/anything/the/router/owns")
    assert answer.status_code == 200
    assert answer.text == INDEX_HTML


def test_a_hashed_asset_is_served_as_itself(served: TestClient) -> None:
    answer = served.get("/assets/app-abc123.js")
    assert answer.status_code == 200
    assert answer.text == BUNDLE_JS


# ------------------------------------------------------------- what the page is never served for


@pytest.mark.parametrize(
    "path",
    [
        "/api/there-is-no-such-route",
        "/api/cases/not-a-uuid/nonsense",
        "/events/nope",
        "/internal/intents/report",
        "/internal",
        "/healthz/extra",
        "/readyz/extra",
    ],
)
def test_a_path_this_process_owns_is_never_answered_with_the_page(
    served: TestClient, path: str
) -> None:
    """An API client that mistypes a path must be told so, in the shape it expects.

    Answering HTML with status 200 here is the failure that makes a caller report a bug about
    the wrong system: nothing errored, the body simply was not what anybody asked for.
    """
    answer = served.get(path)
    assert answer.status_code == 404
    assert answer.json()["error"]["code"] == "NOT_FOUND"
    assert "<html" not in answer.text


def test_the_health_endpoints_still_answer_themselves(served: TestClient) -> None:
    assert served.get("/healthz").json()["service"] == "api"


def test_a_write_to_an_unknown_path_is_refused_rather_than_shown_the_page(
    served: TestClient,
) -> None:
    """A POST is never a page request, and the answer should be the one it had before."""
    answer = served.post("/whatever", json={})
    assert answer.status_code == 404
    assert "<html" not in answer.text


def test_a_path_that_climbs_out_of_the_bundle_gets_the_page_and_not_the_file(
    served: TestClient, bundle: Path
) -> None:
    """The request path is attacker-controlled text, so containment is checked after resolving."""
    answer = served.get("/assets/..%2f..%2foutside-the-bundle.txt")
    assert answer.status_code == 200
    assert "not yours" not in answer.text


# ------------------------------------------------------------------------------------- caching


def test_a_hashed_asset_may_be_kept_forever(served: TestClient) -> None:
    assert served.get("/assets/app-abc123.js").headers["cache-control"] == IMMUTABLE


def test_the_index_is_never_stored(served: TestClient) -> None:
    """The one staleness that is fatal: an index naming a bundle the next release deleted."""
    assert served.get("/").headers["cache-control"] == NEVER_STORED
    assert served.get("/some/deep/link").headers["cache-control"] == NEVER_STORED


def test_a_file_that_is_not_named_by_its_hash_is_not_kept(served: TestClient) -> None:
    assert served.get("/favicon.svg").headers["cache-control"] == NEVER_STORED


# ------------------------------------------------------------------------ when there is no bundle


def test_without_a_bundle_the_api_serves_no_page_at_all(client: TestClient) -> None:
    """The default everywhere but the deployed image, including in every other test here."""
    answer = client.get("/")
    assert answer.status_code == 404
    assert "<html" not in answer.text


def test_a_configured_directory_with_no_index_refuses_to_start(tmp_path: Path) -> None:
    """Better than a working API behind a blank page nobody notices until they open it."""
    empty = tmp_path / "built-wrong"
    empty.mkdir()
    with pytest.raises(RuntimeError, match="holds no index"):
        create_app(Settings(static_root=empty))
