"""Conservative URL identity: retain meaningful query parameters and path case."""
from hashlib import sha256
from app.core.url_identity_v1 import canonicalize_url


def identity_hash(value: str) -> str:
    return sha256(value.encode("utf-8")).hexdigest()


