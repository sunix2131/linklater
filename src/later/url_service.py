from __future__ import annotations

import ipaddress
from dataclasses import dataclass
from urllib.parse import parse_qsl, quote, unquote, urlencode, urlsplit, urlunsplit

import idna

TRACKING_KEYS = {"fbclid", "gclid", "mc_cid", "mc_eid", "yclid", "_ga"}
BLOCKED_SCHEMES = {"file", "javascript", "data", "mailto", "tel", "ftp", "chrome", "about"}


class UrlError(ValueError):
    pass


@dataclass(frozen=True)
class NormalizedUrl:
    original: str
    normalized: str
    domain: str


class UrlNormalizationService:
    def normalize(self, value: str, *, allow_local: bool = False) -> NormalizedUrl:
        original = value.strip()
        if not original:
            raise UrlError("Введите URL.")
        try:
            raw_scheme = urlsplit(original).scheme.lower()
        except ValueError as exc:
            raise UrlError("Ссылка имеет неподдерживаемый формат.") from exc
        if raw_scheme in BLOCKED_SCHEMES:
            raise UrlError("Ссылка имеет неподдерживаемый формат.")
        candidate = original if "://" in original else f"https://{original}"
        parts = urlsplit(candidate)
        scheme = parts.scheme.lower()
        if scheme in BLOCKED_SCHEMES or scheme not in {"http", "https"}:
            raise UrlError("Ссылка имеет неподдерживаемый формат.")
        if not parts.hostname:
            raise UrlError("В ссылке не найден домен.")
        if parts.username is not None or parts.password is not None:
            raise UrlError("Ссылки с логином или паролем не поддерживаются.")

        host = parts.hostname.rstrip(".").lower()
        try:
            ascii_host = str(ipaddress.ip_address(host))
        except ValueError:
            try:
                ascii_host = idna.encode(host).decode("ascii")
            except idna.IDNAError as exc:
                raise UrlError("Домен в ссылке некорректен.") from exc
        if not allow_local and self._is_local(ascii_host):
            raise UrlError("Локальные и сетевые URL отключены в настройках.")

        try:
            port = parts.port
        except ValueError as exc:
            raise UrlError("Порт в ссылке некорректен.") from exc
        netloc = f"[{ascii_host}]" if ":" in ascii_host else ascii_host
        if port and not ((scheme == "http" and port == 80) or (scheme == "https" and port == 443)):
            netloc = f"{netloc}:{port}"
        path = quote(unquote(parts.path or "/"), safe="/:@!$&'()*+,;=-._~")
        query_items = [
            (key, val)
            for key, val in parse_qsl(parts.query, keep_blank_values=True)
            if not key.lower().startswith("utm_") and key.lower() not in TRACKING_KEYS
        ]
        query = urlencode(sorted(query_items), doseq=True)
        normalized = urlunsplit((scheme, netloc, path, query, ""))
        return NormalizedUrl(original=candidate, normalized=normalized, domain=ascii_host)

    def _is_local(self, host: str) -> bool:
        if host == "localhost" or host.endswith((".local", ".localhost")):
            return True
        try:
            ip = ipaddress.ip_address(host.strip("[]"))
        except ValueError:
            return "." not in host
        return not ip.is_global or ip.is_multicast
