import httpx


def test_health_exact(base_url: str) -> None:
    r = httpx.get(f"{base_url}/health", timeout=5)
    assert r.status_code == 200
    assert r.json() == {"status": "ok", "version": "0.1.0", "pipeline_mode": "stub"}
