"""Safe, stable source errors. Never include response bodies, IPs or credentials."""

_MESSAGES = {
    "unsafe_destination": "Source destination was blocked by outbound security policy.",
    "timeout": "Source request exceeded its time limit.",
    "dns_error": "Source hostname could not be resolved.",
    "network_error": "Source connection failed.",
    "http_rejected": "Source rejected the HTTP request.",
    "invalid_json": "Source returned a non-JSON or invalid JSON response.",
    "malformed_structure": "Source returned an unexpected response structure.",
    "normalization_filtered": "Source returned entries but none were usable articles.",
    "response_too_large": "Source response exceeded the size limit.",
    "redirect_limit": "Source exceeded the redirect limit.",
    "unsupported_encoding": "Source returned an unsupported content encoding.",
}


class SourceFetchError(Exception):
    def __init__(self, code: str, *, status_code: int | None = None):
        self.code = code
        self.status_code = status_code
        message = _MESSAGES[code]
        if status_code is not None:
            message += f" HTTP {status_code}."
        super().__init__(f"{code}: {message}")


class SourceSecurityError(SourceFetchError):
    def __init__(self):
        super().__init__("unsafe_destination")
