"""Node/PptxGenJS presentation renderer adapter."""

import json
import os
import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any


class RendererError(Exception):
    def __init__(self, message: str, *, retryable: bool = False) -> None:
        super().__init__(message)
        self.retryable = retryable


def _repository_root() -> Path:
    configured = os.getenv("FINANCIAL_SLIDES_REPOSITORY_ROOT")
    return Path(configured) if configured else Path(__file__).resolve().parents[5]


class NodePresentationRenderer:
    def __init__(self, *, timeout_seconds: float = 30) -> None:
        self._timeout_seconds = timeout_seconds

    def render(self, slide_spec: dict[str, Any]) -> bytes:
        root = _repository_root()
        cli = root / "packages/presentation-renderer/src/cli.mjs"
        with TemporaryDirectory(prefix="financial-slides-") as directory:
            output = Path(directory) / "presentation.pptx"
            try:
                completed = subprocess.run(
                    ["node", str(cli), str(output)],
                    cwd=root,
                    input=json.dumps(slide_spec),
                    text=True,
                    capture_output=True,
                    timeout=self._timeout_seconds,
                    check=False,
                )
            except (OSError, subprocess.TimeoutExpired) as error:
                raise RendererError(
                    "presentation renderer was unavailable",
                    retryable=True,
                ) from error
            if completed.returncode != 0 or not output.is_file():
                raise RendererError("presentation rendering failed", retryable=True)
            return output.read_bytes()
