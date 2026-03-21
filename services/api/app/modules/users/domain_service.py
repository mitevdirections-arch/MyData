from __future__ import annotations

from app.modules.users.service import UsersService, service

DomainUsersService = UsersService

__all__ = ["UsersService", "DomainUsersService", "service"]
