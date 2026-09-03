from httpx import ASGITransport, AsyncClient

from app.main import app


async def test_health() -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


async def test_taxonomies() -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/v1/taxonomies")
    assert response.status_code == 200
    assert response.json()["version"] == "taxonomy-v1"
