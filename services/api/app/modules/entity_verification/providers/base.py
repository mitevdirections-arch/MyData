from __future__ import annotations

from abc import ABC, abstractmethod

from app.modules.entity_verification.schemas import ProviderCheckResultDTO, VerificationTargetDTO


class VerificationProviderBase(ABC):
    provider_code: str
    check_type: str

    @abstractmethod
    def run_check(
        self,
        *,
        target: VerificationTargetDTO,
        request_id: str | None = None,
    ) -> ProviderCheckResultDTO:
        """Run provider check and return unified result contract."""

