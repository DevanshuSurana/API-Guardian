
# ============================================================
# API Guardian - GitHub Permissions Service
# File: backend/services/github_permissions_service.py
#
# Purpose:
#   Evaluate repository access permissions using GitHub
#   repository metadata.
#
# Python: 3.10+
# ============================================================

from typing import Any


def evaluate_repository_permissions(
    repository_data: dict[str, Any],
) -> dict[str, Any]:
    """Evaluate GitHub repository permissions."""

    permissions = repository_data.get("permissions") or {}

    can_read = bool(permissions.get("pull", False))
    can_push = bool(permissions.get("push", False))
    is_admin = bool(permissions.get("admin", False))

    return {
        "repository": repository_data.get("full_name"),
        "can_read": can_read,
        "can_push": can_push,
        "is_admin": is_admin,
        "can_prepare_pull_request": can_push,
    }
