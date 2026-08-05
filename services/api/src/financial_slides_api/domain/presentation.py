"""Immutable presentation-density contract shared across generation stages."""

from dataclasses import asdict, dataclass
from enum import StrEnum
from types import MappingProxyType
from typing import Any, Mapping


class PresentationDensity(StrEnum):
    CONCISE = "concise"
    BALANCED = "balanced"
    DETAILED = "detailed"


@dataclass(frozen=True)
class DensityConstraints:
    max_insights_per_slide: int
    max_bullets_per_slide: int
    max_table_rows: int
    chart_preference: str
    speaker_notes_depth: str
    appendix_policy: str
    min_font_size: int
    min_spacing: int
    max_auto_fit_passes: int
    max_repair_attempts: int

    def as_contract(self) -> dict[str, Any]:
        values = asdict(self)
        return {
            "maxInsightsPerSlide": values.pop("max_insights_per_slide"),
            "maxBulletsPerSlide": values.pop("max_bullets_per_slide"),
            "maxTableRows": values.pop("max_table_rows"),
            "chartPreference": values.pop("chart_preference"),
            "speakerNotesDepth": values.pop("speaker_notes_depth"),
            "appendixPolicy": values.pop("appendix_policy"),
            "preflight": {
                "minFontSize": values.pop("min_font_size"),
                "minSpacing": values.pop("min_spacing"),
                "maxAutoFitPasses": values.pop("max_auto_fit_passes"),
                "maxRepairAttempts": values.pop("max_repair_attempts"),
            },
        }


DENSITY_PROFILES: Mapping[PresentationDensity, DensityConstraints] = MappingProxyType(
    {
        PresentationDensity.CONCISE: DensityConstraints(
            max_insights_per_slide=1,
            max_bullets_per_slide=3,
            max_table_rows=5,
            chart_preference="essential-only",
            speaker_notes_depth="minimal",
            appendix_policy="only-when-needed",
            min_font_size=18,
            min_spacing=6,
            max_auto_fit_passes=1,
            max_repair_attempts=1,
        ),
        PresentationDensity.BALANCED: DensityConstraints(
            max_insights_per_slide=2,
            max_bullets_per_slide=5,
            max_table_rows=8,
            chart_preference="when-useful",
            speaker_notes_depth="standard",
            appendix_policy="evidence-dependent",
            min_font_size=16,
            min_spacing=4,
            max_auto_fit_passes=2,
            max_repair_attempts=2,
        ),
        PresentationDensity.DETAILED: DensityConstraints(
            max_insights_per_slide=3,
            max_bullets_per_slide=7,
            max_table_rows=12,
            chart_preference="when-supported",
            speaker_notes_depth="rich",
            appendix_policy="include-when-supported",
            min_font_size=16,
            min_spacing=4,
            max_auto_fit_passes=2,
            max_repair_attempts=2,
        ),
    }
)


def resolve_density_profile(
    density: PresentationDensity | str = PresentationDensity.BALANCED,
) -> tuple[PresentationDensity, DensityConstraints]:
    profile = density if isinstance(density, PresentationDensity) else PresentationDensity(density)
    return profile, DENSITY_PROFILES[profile]


def resolve_slide_count(requested: int) -> int:
    if not 4 <= requested <= 20:
        raise ValueError("slide_count must be between 4 and 20")
    return requested
