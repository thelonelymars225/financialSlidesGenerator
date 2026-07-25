"""Provider boundary for financial-analysis orchestration."""

from collections.abc import Sequence
from typing import Protocol

from financial_slides_api.domain.analysis import AnalysisRequest, ProviderAnalysis


class AnalysisProvider(Protocol):
    async def analyze(
        self,
        request: AnalysisRequest,
        validation_feedback: Sequence[str],
    ) -> ProviderAnalysis: ...
