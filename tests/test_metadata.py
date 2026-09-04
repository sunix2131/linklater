from __future__ import annotations

import httpx
import respx

from later.metadata import MAX_FAVICON_SIZE, MetadataClient


@respx.mock
def test_fetches_page_metadata_and_same_domain_favicon(tmp_path) -> None:
    respx.get("https://example.com/article").mock(
        return_value=httpx.Response(
            200,
            headers={"content-type": "text/html; charset=utf-8"},
            text=(
                "<html><head><title>Fallback title</title>"
                '<meta property="og:title" content="Paper title">'
                '<meta name="description" content="Paper description">'
                '<link rel="icon" href="/favicon.png">'
                "</head></html>"
            ),
        )
    )
    respx.get("https://example.com/favicon.png").mock(
        return_value=httpx.Response(200, headers={"content-type": "image/png"}, content=b"png")
    )

    result = MetadataClient(tmp_path).fetch(
        "https://example.com/article", "https://example.com/article", "example.com"
    )

    assert result.title == "Paper title"
    assert result.description == "Paper description"
    assert result.favicon_path is not None
    assert (tmp_path / result.favicon_path.split("/")[-1]).read_bytes() == b"png"


@respx.mock
def test_does_not_request_cross_domain_favicon(tmp_path) -> None:
    respx.get("https://example.com/article").mock(
        return_value=httpx.Response(
            200,
            headers={"content-type": "text/html"},
            text='<html><head><title>Page</title><link rel="icon" href="https://cdn.example.net/icon.png"></head></html>',
        )
    )

    result = MetadataClient(tmp_path).fetch(
        "https://example.com/article", "https://example.com/article", "example.com"
    )

    assert result.title == "Page"
    assert result.favicon_path is None


@respx.mock
def test_rejects_oversized_favicon(tmp_path) -> None:
    respx.get("https://example.com/article").mock(
        return_value=httpx.Response(
            200,
            headers={"content-type": "text/html"},
            text='<html><head><title>Page</title><link rel="icon" href="/favicon.ico"></head></html>',
        )
    )
    respx.get("https://example.com/favicon.ico").mock(
        return_value=httpx.Response(
            200,
            headers={"content-type": "image/x-icon"},
            content=b"x" * (MAX_FAVICON_SIZE + 1),
        )
    )

    result = MetadataClient(tmp_path).fetch(
        "https://example.com/article", "https://example.com/article", "example.com"
    )

    assert result.favicon_path is None
    assert list(tmp_path.iterdir()) == []
