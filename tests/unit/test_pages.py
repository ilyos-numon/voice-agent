from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app.main import create_app


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(create_app()) as c:
        yield c


def test_root_is_home_page(client: TestClient) -> None:
    res = client.get("/")
    assert res.status_code == 200
    assert res.headers["content-type"].startswith("text/html")
    assert 'data-page="home"' in res.text
    assert 'id="timings"' not in res.text


def test_talk_page(client: TestClient) -> None:
    res = client.get("/talk?agent=x")
    assert res.status_code == 200
    assert res.headers["content-type"].startswith("text/html")
    assert 'data-page="talk"' in res.text


def test_kiosk_demo_still_served(client: TestClient) -> None:
    res = client.get("/static/index.html")
    assert res.status_code == 200
    assert 'id="timings"' in res.text


def test_builder_page_removed(client: TestClient) -> None:
    assert client.get("/static/builder.html").status_code == 404
