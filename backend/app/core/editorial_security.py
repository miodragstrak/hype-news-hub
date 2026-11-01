"""Provider-neutral editorial identities and permissions; no credential verifier is enabled."""
from dataclasses import dataclass
from enum import Enum
from typing import Protocol


class EditorialRole(str, Enum):
    READER = "reader"
    EDITOR = "editor"
    REVIEWER = "reviewer"
    PUBLISHER = "publisher"
    ADMINISTRATOR = "administrator"


class EditorialPermission(str, Enum):
    READ = "editorial:read"
    EDIT = "editorial:edit"
    SUBMIT = "editorial:submit"
    REVIEW = "editorial:review"
    DELIVER = "editorial:deliver"
    ADMINISTER = "editorial:administer"


_ROLE_PERMISSIONS = {
    EditorialRole.READER: frozenset({EditorialPermission.READ}),
    EditorialRole.EDITOR: frozenset({EditorialPermission.READ, EditorialPermission.EDIT, EditorialPermission.SUBMIT}),
    EditorialRole.REVIEWER: frozenset({EditorialPermission.READ, EditorialPermission.REVIEW}),
    EditorialRole.PUBLISHER: frozenset({EditorialPermission.READ, EditorialPermission.DELIVER}),
    EditorialRole.ADMINISTRATOR: frozenset(EditorialPermission),
}


@dataclass(frozen=True)
class EditorialPrincipal:
    issuer: str
    subject: str
    roles: frozenset[EditorialRole]

    def __post_init__(self):
        for value in (self.issuer, self.subject):
            if not isinstance(value, str) or not value.strip() or len(value) > 512 or any(ord(c) < 32 for c in value):
                raise ValueError("Verified identities require a nonempty issuer and subject.")
        if not isinstance(self.roles, frozenset) or any(not isinstance(role, EditorialRole) for role in self.roles):
            raise ValueError("Roles must be mapped by the server-side identity verifier.")

    @property
    def permissions(self) -> frozenset[EditorialPermission]:
        return frozenset(permission for role in self.roles for permission in _ROLE_PERMISSIONS[role])


class InvalidEditorialIdentity(Exception):
    """Expired, invalid, revoked or otherwise unverifiable credentials."""


class EditorialIdentityUnavailable(Exception):
    """Verification is not configured or the verification service is unavailable."""


class EditorialIdentityVerifier(Protocol):
    async def verify(self, bearer_token: str) -> EditorialPrincipal:
        """Verify credentials and map trusted identity/roles; never trust caller role headers."""
        ...


class UnconfiguredEditorialIdentityVerifier:
    async def verify(self, bearer_token: str) -> EditorialPrincipal:
        raise EditorialIdentityUnavailable()
