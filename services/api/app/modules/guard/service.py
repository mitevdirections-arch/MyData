from __future__ import annotations

from app.modules.guard.service_parts import (
    VALID_HEARTBEAT_EVENTS,
    GuardBotChecksMixin,
    GuardBotCredentialMixin,
    GuardHeartbeatMixin,
    GuardSecurityLeaseMixin,
    GuardSharedMixin,
)


class GuardService(
    GuardSharedMixin,
    GuardHeartbeatMixin,
    GuardBotCredentialMixin,
    GuardBotChecksMixin,
    GuardSecurityLeaseMixin,
):
    """Compatibility facade preserving the original public service contract."""


service = GuardService()
