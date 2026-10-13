from pathlib import Path

from httpx import ASGITransport, AsyncClient

from app.main import create_app


async def test_serves_web_and_keeps_api_first(tmp_path: Path) -> None:
    (tmp_path / "index.html").write_text("<title>loadline</title>")
    app = create_app(static_dir=str(tmp_path))

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        page = await client.get("/")
        health = await client.get("/health")

    assert page.status_code == 200
    assert "<title>loadline</title>" in page.text
    assert health.status_code == 200


async def test_without_static_dir_root_is_404() -> None:
    app = create_app(static_dir="")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        res = await client.get("/")

    assert res.status_code == 404
