"""AUTOMATED TEST FIXTURE ONLY. Not imported by app or copied into runtime images.

Opaque fixture tokens map to identities here; this is deliberately not a JWT or
production credential verifier. No environment/header switch can install it.
"""
from app.core.editorial_security import (
    EditorialIdentityUnavailable, EditorialPrincipal, EditorialRole, InvalidEditorialIdentity,
)


class TestIdentityVerifier:
    def __init__(self):
        self.calls = []
        self.identities = {
            f"fixture-{role.value}": EditorialPrincipal("urn:hnh:test", f"test-{role.value}", frozenset({role}))
            for role in EditorialRole
        }
        self.identities["fixture-no-roles"] = EditorialPrincipal("urn:hnh:test", "no-roles", frozenset())

    async def verify(self, bearer_token):
        self.calls.append(bearer_token)
        if bearer_token == "fixture-unavailable":
            raise EditorialIdentityUnavailable("sensitive provider details")
        if bearer_token == "fixture-broken":
            raise RuntimeError("sensitive verification secret")
        if bearer_token == "fixture-wrong-return":
            return {"subject": "untrusted", "roles": ["administrator"]}
        if bearer_token not in self.identities:
            raise InvalidEditorialIdentity("sensitive token claims")
        return self.identities[bearer_token]
