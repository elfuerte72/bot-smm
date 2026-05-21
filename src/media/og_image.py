from __future__ import annotations

import asyncio
import io
from dataclasses import dataclass
from urllib.parse import urljoin

import httpx
from bs4 import BeautifulSoup
from loguru import logger
from PIL import Image, UnidentifiedImageError

TELEGRAM_PHOTO_MAX_BYTES = 10 * 1024 * 1024  # 10 MB
DEFAULT_TIMEOUT = httpx.Timeout(15.0, connect=10.0)
DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9,ru;q=0.8",
}

# Картинка считается «вероятно логотипом», если она почти квадратная и при этом
# маленькая (меньше 1200 px по большей стороне). Корпоративные логотипы обычно
# отдаются как 600x600 или 1000x1000. Большие фото статей чаще 1200x630
# (Open Graph spec) или шире.
_LOGO_ASPECT_MIN = 0.85
_LOGO_ASPECT_MAX = 1.18
_LOGO_MAX_SIDE = 1200


@dataclass(slots=True)
class FetchedImage:
    url: str
    content: bytes
    content_type: str
    width: int
    height: int

    @property
    def aspect(self) -> float:
        if self.height == 0:
            return 0.0
        return self.width / self.height

    @property
    def likely_logo(self) -> bool:
        if not self.width or not self.height:
            return False
        if _LOGO_ASPECT_MIN <= self.aspect <= _LOGO_ASPECT_MAX:
            max_side = max(self.width, self.height)
            if max_side < _LOGO_MAX_SIDE:
                return True
        # доп. эвристика по URL
        url_l = self.url.lower()
        if "logo" in url_l or "favicon" in url_l:
            return True
        return False


def _extract_image_url(html: str, base_url: str) -> str | None:
    soup = BeautifulSoup(html, "html.parser")

    candidates = [
        ("meta", {"property": "og:image"}),
        ("meta", {"property": "og:image:url"}),
        ("meta", {"name": "twitter:image"}),
        ("meta", {"name": "twitter:image:src"}),
        ("link", {"rel": "image_src"}),
    ]
    for tag, attrs in candidates:
        node = soup.find(tag, attrs=attrs)
        if not node:
            continue
        val = node.get("content") or node.get("href")
        if val:
            return urljoin(base_url, val.strip())
    return None


def _read_dimensions(content: bytes) -> tuple[int, int] | None:
    try:
        with Image.open(io.BytesIO(content)) as img:
            return img.size
    except (UnidentifiedImageError, OSError):
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

            dims = _read_dimensions(content)
            if dims is None:
                logger.info("Не удалось определить размеры картинки {}", img_url)
                return None

            return FetchedImage(
                url=img_url,
                content=content,
                content_type=ct,
                width=dims[0],
                height=dims[1],
            )
    except (httpx.HTTPError, httpx.InvalidURL) as e:
        logger.warning("Не удалось скачать og:image для {}: {}", url, e)
        return None


async def fetch_best_image(urls: list[str]) -> FetchedImage | None:
    """Перебирает список URL источников, возвращает первую не-логотипную картинку.

    Если все варианты выглядят как логотипы — возвращает первую найденную
    (хоть какая-то картинка лучше, чем пустота). Если вообще ничего не нашли,
    возвращает None.
    """
    first_fallback: FetchedImage | None = None
    for url in urls:
        if not url:
            continue
        img = await fetch_og_image(url)
        if img is None:
            continue
        if not img.likely_logo:
            logger.info(
                "Выбрана картинка с {} ({}x{}, {} bytes)",
                url,
                img.width,
                img.height,
                len(img.content),
            )
            return img
        if first_fallback is None:
            first_fallback = img
        logger.info(
            "Пропускаю похоже-на-логотип с {} ({}x{})",
            url,
            img.width,
            img.height,
        )

    if first_fallback is not None:
        logger.info("Все картинки выглядят как логотипы. Беру первую: {}", first_fallback.url)
    return first_fallback


async def _cli() -> None:
    import sys

    if len(sys.argv) < 2:
        print("Usage: python -m src.media.og_image <url> [<url> ...]")
        sys.exit(1)

    urls = sys.argv[1:]
    result = await fetch_best_image(urls)
    if result is None:
        print("Картинка не найдена ни в одном источнике")
        sys.exit(2)

    out = "/tmp/og.jpg"
    await asyncio.to_thread(_write_bytes, out, result.content)
    print(
        f"OK: {result.url} ({result.content_type}, {result.width}x{result.height}, "
        f"{len(result.content)} bytes, logo={result.likely_logo}) -> {out}"
    )


def _write_bytes(path: str, data: bytes) -> None:
    with open(path, "wb") as f:
        f.write(data)


if __name__ == "__main__":
    asyncio.run(_cli())
