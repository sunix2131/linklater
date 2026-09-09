from __future__ import annotations

import hashlib
import ssl
from pathlib import Path
from urllib.parse import urljoin, urlsplit

import certifi
import httpx
from bs4 import BeautifulSoup

from later.domain import LinkMetadata
from later.url_service import UrlError, UrlNormalizationService

MAX_HTML_SIZE = 2 * 1024 * 1024
MAX_FAVICON_SIZE = 1024 * 1024


class MetadataClient:
    def __init__(self, favicons_dir: Path, timeout_seconds: int = 10, *, allow_local: bool = False) -> None:
        self.favicons_dir = favicons_dir
        self.timeout_seconds = timeout_seconds
        self.allow_local = allow_local

    def _validate_request(self, request: httpx.Request) -> None:
        UrlNormalizationService().normalize(str(request.url), allow_local=self.allow_local)

    def fetch(self, url: str, normalized_url: str, domain: str, *, fetch_favicon: bool = True) -> LinkMetadata:
        try:
            url = UrlNormalizationService().normalize(url, allow_local=self.allow_local).original
            with httpx.Client(
                timeout=self.timeout_seconds,
                follow_redirects=True,
                max_redirects=5,
                verify=ssl.create_default_context(cafile=certifi.where()),
                headers={"User-Agent": "LinkLater/0.1 local metadata fetcher"},
                event_hooks={"request": [self._validate_request]},
            ) as client:
                with client.stream("GET", url) as response:
                    response.raise_for_status()
                    content_type = response.headers.get("content-type", "")
                    if "html" not in content_type.lower():
                        return LinkMetadata(title=domain, error="Страница не является HTML-документом.")
                    html, _ = self._read_limited(response, MAX_HTML_SIZE)
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
                    try:
                        favicon_path = self._fetch_favicon(client, soup, str(response.url), normalized_url, domain)
                    except (httpx.HTTPError, OSError, UrlError):
                        favicon_path = None
                return LinkMetadata(title=title, description=description, favicon_path=favicon_path)
        except Exception as exc:
            return LinkMetadata(title=domain, description="", error=str(exc))

    def _fetch_favicon(
        self, client: httpx.Client, soup: BeautifulSoup, page_url: str, normalized_url: str, domain: str
    ) -> str | None:
        href = None
        for node in soup.find_all("link"):
            rel_value = node.get("rel")
            if isinstance(rel_value, str):
                rel_values = rel_value.split()
            elif rel_value is None:
                rel_values = []
            else:
                rel_values = rel_value
            rel_names = {str(value).lower() for value in rel_values}
            if "icon" in rel_names and node.get("href"):
                href = str(node["href"])
                break
        icon_url = urljoin(page_url, href) if href else f"{urlsplit(page_url).scheme}://{domain}/favicon.ico"
        if urlsplit(icon_url).hostname != domain:
            return None
        with client.stream("GET", icon_url, follow_redirects=False) as response:
            response.raise_for_status()
            if "text/html" in response.headers.get("content-type", "").lower():
                return None
            content, truncated = self._read_limited(response, MAX_FAVICON_SIZE)
            if truncated:
                return None
        self.favicons_dir.mkdir(parents=True, exist_ok=True)
        suffix = Path(urlsplit(icon_url).path).suffix or ".ico"
        name = hashlib.sha256(normalized_url.encode("utf-8")).hexdigest() + suffix[:8]
        path = self.favicons_dir / name
        path.write_bytes(content)
        return str(path)

    def _read_limited(self, response: httpx.Response, limit: int) -> tuple[bytes, bool]:
        content = bytearray()
        for chunk in response.iter_bytes():
            remaining = limit - len(content)
            if len(chunk) > remaining:
                content.extend(chunk[:remaining])
                return bytes(content), True
            content.extend(chunk)
        return bytes(content), False

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
