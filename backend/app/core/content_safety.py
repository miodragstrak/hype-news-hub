"""Plain-text extraction and non-fetching URL validation for untrusted content."""
from html.parser import HTMLParser
from ipaddress import ip_address
import re
from urllib.parse import urlsplit


def safe_content_url(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    value = value.strip()
    if not value or re.search(r"[\x00-\x20\x7f]", value):
        return None
    try:
        parts = urlsplit(value)
        if parts.scheme.lower() not in {"http", "https"} or not parts.hostname or parts.username is not None:
            return None
        if parts.port not in (None, 80, 443) or parts.hostname.lower() == "localhost" or parts.hostname.lower().endswith(".localhost"):
            return None
        try:
            address = ip_address(parts.hostname)
        except ValueError:
            address = None
        if address is not None and (not address.is_global or address.is_multicast or address.is_reserved):
            return None
    except ValueError:
        return None
    return value


class _PlainText(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self.ignored = []

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style", "template", "noscript", "iframe"}:
            self.ignored.append(tag)
        elif not self.ignored and tag in {"p", "br", "div", "li", "h1", "h2", "h3"}:
            self.parts.append(" ")

    def handle_endtag(self, tag):
        if self.ignored and tag == self.ignored[-1]:
            self.ignored.pop()
        elif not self.ignored and tag in {"p", "div", "li", "h1", "h2", "h3"}:
            self.parts.append(" ")

    def handle_data(self, data):
        if not self.ignored:
            self.parts.append(data)


def plain_text(value: str | None) -> str | None:
    if value is None:
        return None
    parser = _PlainText()
    parser.feed(value)
    parser.close()
    return "".join(parser.parts).strip()
