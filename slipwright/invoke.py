from __future__ import annotations

from typing import Any

from slipwright.schemas.profile import Profile, RoleName


class InvokeError(RuntimeError):
    pass


def invoke_role(role: RoleName | str, profile: Profile, context: dict[str, Any]) -> dict[str, Any]:
    """Invoke a role using the profile. This is a lightweight, testable stub.

    - Validates the role exists in the profile.
    - Returns a simple dict that resembles a structured RoleResult.
    """
    # normalize role to RoleName
    if isinstance(role, str):
        try:
            role = RoleName(role)
        except ValueError as exc:
            raise KeyError(f"unknown role: {role}") from exc

    if role not in profile.roles:
        raise KeyError(f"unknown role: {role}")

    role_cfg = profile.roles[role]

    # Minimal stub of structured result; real implementation will call model providers.
    return {
        "role": role.value,
        "result": {"ok": True},
        "summary": f"invoked {role.value} with model {role_cfg.model} at depth {role_cfg.thinking_depth.value}",
        "permissions": [p.value for p in role_cfg.permissions],
        "context": context,
    }


__all__ = ["invoke_role", "InvokeError"]
