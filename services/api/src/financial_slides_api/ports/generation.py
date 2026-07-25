"""Presentation rendering boundary."""

from typing import Any, Protocol


class PresentationArtifactRenderer(Protocol):
    def render(self, slide_spec: dict[str, Any]) -> bytes: ...
