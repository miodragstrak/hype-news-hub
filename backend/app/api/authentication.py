from ipaddress import ip_address, ip_network
import hmac
import logging
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictStr
from starlette.concurrency import run_in_threadpool

from app.services.authentication import AuthError, COOKIE

router = APIRouter()
logger = logging.getLogger(__name__)


class Login(BaseModel):
    model_config = ConfigDict(extra="forbid")
    email: StrictStr = Field(min_length=1, max_length=254)
    password: StrictStr = Field(min_length=1, max_length=128)


class CreateUser(Login):
    role: Literal["admin", "editor"]


class ChangeUser(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_revision: int = Field(strict=True, ge=1)
    role: Literal["admin", "editor"]
    active: StrictBool


def proxy_networks(value):
    try:
        networks = [ip_network(item.strip(), strict=False) for item in value.split(",")]
        if not networks or any(n.prefixlen == 0 for n in networks):
            raise ValueError()
        return networks
    except ValueError:
        raise ValueError("Explicit trusted Nginx proxy IPs/CIDRs are required.") from None


def client_address(request, networks):
    try:
        peer = ip_address(request.client.host)
        if any(peer in n for n in networks):
            values = request.headers.getlist("x-real-ip")
            if len(values) != 1:
                raise ValueError()
            return str(ip_address(values[0]))
        return str(peer)  # Ignore every forwarding header from untrusted peers.
    except (ValueError, AttributeError):
        raise AuthError(503, "Authentication is unavailable.") from None


def check_origin(request, origin, *, allow_missing=False):
    origins = request.headers.getlist("origin")
    if (origins != [origin] and not (allow_missing and not origins)) or request.headers.get("sec-fetch-site") not in (None, "same-origin"):
        raise AuthError(403, "Request rejected.")


def clear_cookie(response):
    response.delete_cookie(COOKIE, path="/", secure=True, httponly=True, samesite="lax")


def install_authentication(application, service, verifier, config):
    networks = proxy_networks(config.auth_trusted_proxy_ips)
    application.state.cookie_auth_enabled = True
    original_openapi = application.openapi

    def cookie_openapi():
        schema = original_openapi()
        schemes = schema.setdefault("components", {}).setdefault("securitySchemes", {})
        schemes.pop("EditorialBearer", None)
        schemes["CookieSession"] = {"type": "apiKey", "in": "cookie", "name": COOKIE}
        for path, operations in schema["paths"].items():
            for method, operation in operations.items():
                if method in {"get", "post", "patch", "put", "delete", "options", "head"}:
                    operation["security"] = [] if path == "/" or (path == "/api/auth/login" and method == "post") else [{"CookieSession": []}]
        return schema

    application.openapi = cookie_openapi

    @application.exception_handler(AuthError)
    async def auth_error(request, exc):
        return JSONResponse({"detail": exc.detail}, status_code=exc.status,
                            headers={"Cache-Control": "no-store", **({"Retry-After": "60"} if exc.status == 429 else {})})

    @application.middleware("http")
    async def session_guard(request, call_next):
        path, method = request.url.path, request.method
        if (path, method) in {("/", "GET"), ("/ready", "GET")}:
            return await call_next(request)
        try:
            if request.headers.get("authorization"):
                raise AuthError()  # Cookie composition cannot be switched to a caller-supplied bearer identity.
            if path.startswith(("/api/auth/", "/api/admin/")) and method not in {"GET", "HEAD"}:
                body = bytearray()
                async for chunk in request.stream():
                    body.extend(chunk)
                    if len(body) > 16384:
                        raise AuthError(413, "Request too large.")
                request._body = bytes(body)
            if (path, method) == ("/api/auth/login", "POST"):
                check_origin(request, config.backend_cors_origins)
                request.state.login_address = client_address(request, networks)
            else:
                try:
                    context = await run_in_threadpool(verifier.resolve, request.cookies.get(COOKIE))
                except AuthError:
                    if (path, method) != ("/api/auth/logout", "POST"):
                        raise
                    context = None  # Idempotent clearing of an already expired/revoked cookie.
                request.state.auth_session = context
                if context is not None:
                    request.state.editorial_principal = context.principal
                mutation = method not in {"GET", "HEAD", "OPTIONS"} or path == "/api/collect"
                if mutation:
                    check_origin(request, config.backend_cors_origins, allow_missing=method == "GET")
                    if context and not hmac.compare_digest(request.headers.get("x-csrf-token", "").encode("utf8"), context.csrf.encode("ascii")):
                        raise AuthError(403, "Request rejected.")
                if path.startswith("/api/admin/") and (context is None or context.account["role"] != "admin"):
                    raise AuthError(403, "Permission denied.")
                if path.endswith("/generate-demo-draft"):
                    raise AuthError(403, "Legacy demo generation is disabled in the operational newsroom.")
            response = await call_next(request)
            response.headers["Cache-Control"] = "no-store"
            return response
        except AuthError as exc:
            headers = {"Cache-Control": "no-store"}
            if exc.status == 429:
                headers["Retry-After"] = "60"
            return JSONResponse({"detail": exc.detail}, status_code=exc.status, headers=headers)
        except Exception as exc:
            logger.warning("Session authentication unavailable (%s)", type(exc).__name__)
            return JSONResponse({"detail": "Authentication is unavailable."}, status_code=503,
                                headers={"Cache-Control": "no-store"})


@router.post("/api/auth/login")
def login(command: Login, request: Request):
    service = request.app.state.authentication
    token = service.login(command.email, command.password, request.state.login_address)
    context = service.resolve(token)
    from fastapi.encoders import jsonable_encoder
    response = JSONResponse(jsonable_encoder({"user": context.account, "csrf_token": context.csrf}))
    response.set_cookie(COOKIE, token, max_age=service.repository.config.auth_session_seconds,
                        path="/", secure=True, httponly=True, samesite="lax")
    return response


@router.get("/api/auth/session")
def session(request: Request):
    context = request.state.auth_session
    return {"user": context.account, "csrf_token": context.csrf}


@router.post("/api/auth/logout", status_code=204)
def logout(request: Request):
    if request.state.auth_session:
        request.app.state.authentication.logout(request.state.auth_session)
    response = Response(status_code=204)
    clear_cookie(response)
    return response


@router.get("/api/admin/users")
def users(request: Request, limit: Annotated[int, Query(ge=1, le=50)] = 20,
          offset: Annotated[int, Query(ge=0, le=10000)] = 0):
    return request.app.state.authentication.users(request.state.auth_session, limit, offset)


@router.post("/api/admin/users", status_code=201)
def create_user(command: CreateUser, request: Request):
    return request.app.state.authentication.create_user(request.state.auth_session, command.email, command.password, command.role)


@router.patch("/api/admin/users/{user_id}")
def change_user(user_id: UUID, command: ChangeUser, request: Request):
    return request.app.state.authentication.update_user(request.state.auth_session, user_id, command.expected_revision, command.role, command.active)
