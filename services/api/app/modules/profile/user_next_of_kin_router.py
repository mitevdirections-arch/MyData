from __future__ import annotations

from app.modules.users.router_parts.next_of_kin import (
    create_user_next_of_kin,
    delete_user_next_of_kin,
    list_user_next_of_kin,
    router,
    update_user_next_of_kin,
)

__all__ = [
    "router",
    "list_user_next_of_kin",
    "create_user_next_of_kin",
    "update_user_next_of_kin",
    "delete_user_next_of_kin",
]
