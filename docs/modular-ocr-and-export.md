# Modular OCR and presentation export

The production baseline is local-first and adapter-driven. Native PDF parsing
is attempted before OCR, Tesseract runs as a bounded subprocess, and no paid
provider is called unless an optional page fallback is explicitly configured.
Both Docker runtime images install Tesseract and English language data.

## OCR boundaries

Use `ExtractionService` when the input is a PDF or pasted text and the consumer
wants the canonical Extracted Document v0.1 contract. It accepts replaceable
`FileExtractor` implementations, and `PdfPlumberExtractor` accepts any
structurally compatible `OcrEngine`.

Use the smaller facade when another system already has an image pipeline:

```python
from financial_slides_worker import LocalOcrService, OcrImageLimits

ocr = LocalOcrService(
    limits=OcrImageLimits(
        max_image_bytes=10 * 1024 * 1024,
        max_pixels=25_000_000,
        timeout_seconds=15,
    )
)
page = ocr.extract_image(png_bytes, width_px=1600, height_px=2200)
```

`OcrPage` contains immutable words, coordinates, confidences, and optional
tables. Callers can inject another image OCR engine without changing the facade.
The default engine invokes Tesseract without a shell and enforces a deadline.

## Presentation export boundaries

Use the in-memory API when the caller owns storage or transport:

```js
import { exportPresentation } from "@financial-slides/presentation-renderer";

const artifact = await exportPresentation(deckSpec);
await objectStore.put(key, artifact.data, { contentType: artifact.mediaType });
```

The artifact includes `data`, `format`, `fileExtension`, `mediaType`, and
deduplicated warnings. `createPresentationExporter(format)` is the format
factory; unsupported formats fail explicitly instead of silently changing the
output.

Existing process integrations can keep the file wrapper:

```js
import { PresentationRenderer } from "@financial-slides/presentation-renderer";

await new PresentationRenderer().render(deckSpec, {
  outputPath: "/private/output/report.pptx",
});
```

The OCR output contract, analysis contract, DeckSpec contract, and exporter are
separate layers. A larger system can replace storage, queues, OCR providers,
analysis providers, or the presentation format independently.

## Production constraints

- Keep OCR and extraction limits lower than the surrounding request timeout.
- Run API and worker containers with CPU and memory limits; OCR is local CPU
  work even though its external-service cost is zero.
- Keep hosted document/VLM fallback disabled unless retention, page selection,
  retry, token, and cost limits are configured.
- Validate Extracted Document and DeckSpec payloads at service boundaries.
- Store exported artifacts privately and apply the repository retention policy.
