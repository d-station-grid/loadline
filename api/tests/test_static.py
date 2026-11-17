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


async def test_index_is_revalidated_and_hashed_assets_are_cached(tmp_path: Path) -> None:
    (tmp_path / "index.html").write_text("<title>loadline</title>")
    (tmp_path / "favicon.svg").write_text("<svg></svg>")
    (tmp_path / "assets").mkdir()
    (tmp_path / "assets" / "index-BMfMf7PA.js").write_text("console.log(1)")
    app = create_app(static_dir=str(tmp_path))

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        root = await client.get("/")
        index = await client.get("/index.html")
        favicon = await client.get("/favicon.svg")
        script = await client.get("/assets/index-BMfMf7PA.js")
        revalidated = await client.get("/", headers={"If-None-Match": root.headers["etag"]})

    assert root.headers["cache-control"] == "no-cache"
    assert index.headers["cache-control"] == "no-cache"
    assert favicon.headers["cache-control"] == "no-cache"
    assert script.headers["cache-control"] == "public, max-age=31536000, immutable"
    assert revalidated.status_code == 304
    assert revalidated.headers["cache-control"] == "no-cache"


async def test_missing_asset_with_404_page_is_not_cached(tmp_path: Path) -> None:
    (tmp_path / "index.html").write_text("<title>loadline</title>")
    (tmp_path / "404.html").write_text("<title>not found</title>")
    (tmp_path / "assets").mkdir()
    app = create_app(static_dir=str(tmp_path))

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        missing = await client.get("/assets/missing.js")

    assert missing.status_code == 404
    assert "not found" in missing.text
    assert missing.headers["cache-control"] == "no-cache"


async def test_api_responses_get_no_static_cache_header(tmp_path: Path) -> None:
    (tmp_path / "index.html").write_text("<title>loadline</title>")
    app = create_app(static_dir=str(tmp_path))

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        health = await client.get("/health")

    assert "cache-control" not in health.headers


async def test_without_static_dir_root_is_404() -> None:
    app = create_app(static_dir="")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        res = await client.get("/")

    assert res.status_code == 404
