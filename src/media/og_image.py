from __future__ import annotations

import asyncio
from dataclasses import dataclass
from urllib.parse import urljoin

import httpx
from bs4 import BeautifulSoup
from loguru import logger

TELEGRAM_PHOTO_MAX_BYTES = 10 * 1024 * 1024  # 10 MB
DEFAULT_TIMEOUT = httpx.Timeout(15.0, connect=10.0)
DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9,ru;q=0.8",
}


@dataclass(slots=True)
class FetchedImage:
    url: str
    content: bytes
    content_type: str


def _extract_image_url(html: str, base_url: str) -> str | None:
    soup = BeautifulSoup(html, "html.parser")

    candidates = [
        ("meta", {"property": "og:image"}),
        ("meta", {"property": "og:image:url"}),
        ("meta", {"name": "twitter:image"}),
        ("meta", {"name": "twitter:image:src"}),
    ]
    for tag, attrs in candidates:
        node = soup.find(tag, attrs=attrs)
        if node and node.get("content"):
            return urljoin(base_url, node["content"].strip())
    return None


async def fetch_og_image(url: str) -> FetchedImage | None:
    """Достаёт URL og:image со страницы и скачивает его. None — если не удалось."""
    try:
        async with httpx.AsyncClient(
            timeout=DEFAULT_TIMEOUT,
            headers=DEFAULT_HEADERS,
            follow_redirects=True,
        ) as client:
            page = await client.get(url)
            page.raise_for_status()
            img_url = _extract_image_url(page.text, str(page.url))
            if not img_url:
                logger.info("og:image не найден на {}", url)
                return None

            img_resp = await client.get(img_url)
            img_resp.raise_for_status()

            content = img_resp.content
            if len(content) > TELEGRAM_PHOTO_MAX_BYTES:
                logger.info(
                    "og:image слишком большой ({} байт > {}). Пропускаю.",
                    len(content),
                    TELEGRAM_PHOTO_MAX_BYTES,
                )
                return None

            ct = img_resp.headers.get("content-type", "image/jpeg").split(";")[0].strip()
            if not ct.startswith("image/"):
                logger.info("Content-Type не image/*: {}", ct)
                return None

            return FetchedImage(url=img_url, content=content, content_type=ct)
    except (httpx.HTTPError, httpx.InvalidURL) as e:
        logger.warning("Не удалось скачать og:image для {}: {}", url, e)
        return None


async def _cli() -> None:
    import sys

    if len(sys.argv) < 2:
        print("Usage: python -m src.media.og_image <url>")
        sys.exit(1)

    url = sys.argv[1]
    result = await fetch_og_image(url)
    if result is None:
        print("og:image не найден")
        sys.exit(2)

    out = "/tmp/og.jpg"
    await asyncio.to_thread(_write_bytes, out, result.content)
    print(f"OK: {result.url} ({result.content_type}, {len(result.content)} bytes) -> {out}")


def _write_bytes(path: str, data: bytes) -> None:
    with open(path, "wb") as f:
        f.write(data)


if __name__ == "__main__":
    asyncio.run(_cli())
