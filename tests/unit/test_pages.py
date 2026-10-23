from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app.main import create_app


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(create_app()) as c:
        yield c


def test_root_redirects_to_studio(client: TestClient) -> None:
    res = client.get("/", follow_redirects=False)
    assert res.status_code == 307
    assert res.headers["location"] == "/studio"


def test_talk_redirects_to_studio_app(client: TestClient) -> None:
    res = client.get("/talk?agent=x", follow_redirects=False)
    assert res.status_code == 307
    assert res.headers["location"] == "/studio/app?agent=x"


def test_studio_page(client: TestClient) -> None:
    res = client.get("/studio")
    assert res.status_code == 200
    assert res.headers["content-type"].startswith("text/html")
    assert 'data-page="studio"' in res.text


def test_studio_app_page(client: TestClient) -> None:
    res = client.get("/studio/app")
    assert res.status_code == 200
    assert res.headers["content-type"].startswith("text/html")
    assert 'data-page="workspace"' in res.text


def test_kiosk_demo_served_from_archive(client: TestClient) -> None:
    res = client.get("/static/archive/kiosk/index.html")
    assert res.status_code == 200
    assert 'id="timings"' in res.text


def test_two_page_talk_served_from_archive(client: TestClient) -> None:
    assert client.get("/static/archive/two-page/talk.html").status_code == 200


def test_old_kiosk_path_removed(client: TestClient) -> None:
    assert client.get("/static/index.html").status_code == 404


def test_builder_page_removed(client: TestClient) -> None:
    assert client.get("/static/builder.html").status_code == 404
