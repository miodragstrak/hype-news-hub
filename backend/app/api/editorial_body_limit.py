"""Bound and validate private JSON commands before FastAPI field validation."""
import json
import math
from itertools import chain

from fastapi.exception_handlers import request_validation_exception_handler
from starlette.responses import JSONResponse

MAX_EDITORIAL_REQUEST_BYTES = 1024 * 1024


async def editorial_validation_error(request, exc):
    if request.url.path.startswith("/api/editorial/"):
        # Default error serialization reflects input/exception objects, which may
        # contain bytes, non-finite floats or lone surrogates. Reflect none of them.
        return JSONResponse({"detail": "Invalid editorial request."}, status_code=422,
                            headers={"Cache-Control": "no-store"})
    return await request_validation_exception_handler(request, exc)


def _finite_float(value):
    number = float(value)
    if not math.isfinite(number):
        raise ValueError("Non-finite JSON number")
    return number


def _reject_constant(value):
    raise ValueError("Non-standard JSON number")


def _validate_json(body):
    parsed = json.loads(body.decode("utf-8-sig"), parse_float=_finite_float, parse_constant=_reject_constant)
    # Iterator frames bound extra traversal memory by depth, even for wide arrays.
    pending = [(iter((parsed,)), 0)]
    while pending:
        iterator, depth = pending[-1]
        try:
            value = next(iterator)
        except StopIteration:
            pending.pop()
            continue
        if depth > 64:
            raise ValueError("JSON nesting limit exceeded")
        if isinstance(value, str):
            value.encode("utf-8", errors="strict")
        elif isinstance(value, dict):
            pending.append((chain(value.keys(), value.values()), depth + 1))
        elif isinstance(value, list):
            pending.append((iter(value), depth + 1))


def _json_content_type(scope):
    values = [value.decode("latin-1") for name, value in scope.get("headers", []) if name.lower() == b"content-type"]
    if not values:
        return True  # Preserve FastAPI's existing JSON behavior when omitted.
    if len(values) != 1:
        return False
    media, *parameters = values[0].lower().split(";")
    media = media.strip()
    if media != "application/json" and not (media.startswith("application/") and media.endswith("+json")):
        return False
    for parameter in parameters:
        name, separator, value = parameter.strip().partition("=")
        if name.strip() == "charset" and (not separator or value.strip().strip('"') not in {"utf-8", "utf8"}):
            return False
    return True


class EditorialBodyLimit:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        path = scope.get("path", "")
        if scope["type"] != "http" or scope.get("method") != "POST" or not (
            path == "/api/editorial/drafts" or path.startswith("/api/editorial/drafts/")
        ):
            return await self.app(scope, receive, send)
        body = bytearray()
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            chunk = message.get("body", b"")
            if len(body) + len(chunk) > MAX_EDITORIAL_REQUEST_BYTES:
                response = JSONResponse({"detail": "Editorial command exceeds the 1 MiB request limit."},
                    status_code=413, headers={"Cache-Control": "no-store"})
                return await response(scope, receive, send)
            body.extend(chunk)
            if not message.get("more_body", False):
                break
        if not _json_content_type(scope):
            response = JSONResponse({"detail": "Editorial commands require UTF-8 JSON content."},
                status_code=415, headers={"Cache-Control": "no-store"})
            return await response(scope, receive, send)
        try:
            _validate_json(body)
        except (ValueError, RecursionError):
            response = JSONResponse({"detail": "Malformed editorial JSON: use valid UTF-8 and finite numbers."},
                status_code=400, headers={"Cache-Control": "no-store"})
            return await response(scope, receive, send)
        consumed = False

        async def replay():
            nonlocal consumed
            if not consumed:
                consumed = True
                return {"type": "http.request", "body": bytes(body), "more_body": False}
            return await receive()

        await self.app(scope, replay, send)
