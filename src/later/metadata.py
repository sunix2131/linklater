from __future__ import annotations

import hashlib
from pathlib import Path
from urllib.parse import urljoin, urlsplit

import certifi
import httpx
from bs4 import BeautifulSoup

from later.domain import LinkMetadata


class MetadataClient:
    def __init__(self, favicons_dir: Path, timeout_seconds: int = 10) -> None:
        self.favicons_dir = favicons_dir
        self.timeout_seconds = timeout_seconds

    def fetch(self, url: str, normalized_url: str, domain: str, *, fetch_favicon: bool = True) -> LinkMetadata:
        try:
            with httpx.Client(
                timeout=self.timeout_seconds,
                follow_redirects=True,
                max_redirects=5,
                verify=certifi.where(),
                headers={"User-Agent": "Later/0.1 local metadata fetcher"},
            ) as client:
                response = client.get(url)
                response.raise_for_status()
                content_type = response.headers.get("content-type", "")
                if "html" not in content_type.lower():
                    return LinkMetadata(title=domain, error="Страница не является HTML-документом.")
                html = response.content[: 2 * 1024 * 1024]
                soup = BeautifulSoup(html, "html.parser")
                title = self._first(
                    self._meta(soup, "property", "og:title"),
                    self._meta(soup, "name", "twitter:title"),
                    soup.title.string.strip() if soup.title and soup.title.string else "",
                    soup.h1.get_text(" ", strip=True) if soup.h1 else "",
                    domain,
                )
                description = self._first(
                    self._meta(soup, "property", "og:description"),
                    self._meta(soup, "name", "description"),
                    self._paragraph(soup),
                    "",
                )
                favicon_path = None
                if fetch_favicon:
                    favicon_path = self._fetch_favicon(client, soup, url, normalized_url, domain)
                return LinkMetadata(title=title, description=description, favicon_path=favicon_path)
        except Exception as exc:
            return LinkMetadata(title=domain, description="", error=str(exc))

    def _fetch_favicon(
        self, client: httpx.Client, soup: BeautifulSoup, page_url: str, normalized_url: str, domain: str
    ) -> str | None:
        href = None
        for rel in ("icon", "shortcut icon"):
            node = soup.find("link", rel=lambda value, rel=rel: value and rel in " ".join(value).lower())
            if node and node.get("href"):
                href = str(node["href"])
                break
        icon_url = urljoin(page_url, href) if href else f"{urlsplit(page_url).scheme}://{domain}/favicon.ico"
        if urlsplit(icon_url).hostname != domain:
            return None
        response = client.get(icon_url)
        response.raise_for_status()
        content = response.content[: 1024 * 1024 + 1]
        if len(content) > 1024 * 1024:
            return None
        suffix = Path(urlsplit(icon_url).path).suffix or ".ico"
        name = hashlib.sha256(normalized_url.encode("utf-8")).hexdigest() + suffix[:8]
        path = self.favicons_dir / name
        path.write_bytes(content)
        return str(path)

    def _meta(self, soup: BeautifulSoup, attr: str, value: str) -> str:
        node = soup.find("meta", attrs={attr: value})
        return str(node.get("content", "")).strip() if node else ""

    def _paragraph(self, soup: BeautifulSoup) -> str:
        for node in soup.find_all(["p", "article"], limit=8):
            text = node.get_text(" ", strip=True)
            if len(text) >= 40:
                return text[:300]
        return ""

    def _first(self, *values: str) -> str:
        return next((value.strip() for value in values if value and value.strip()), "")
