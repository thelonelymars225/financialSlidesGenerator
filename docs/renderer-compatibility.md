# PowerPoint renderer compatibility

## Decision

Use PptxGenJS 4.0.1 as the initial PowerPoint adapter. It creates native
Office Open XML rather than screenshots of complete slides:

- text is emitted as editable text boxes;
- tables are emitted as editable PowerPoint tables;
- bar and line charts are emitted as editable PowerPoint charts;
- images are emitted as selectable raster assets;
- speaker notes are preserved.

The adapter consumes the validated slide-spec contract. Arbitrary HTML is not
accepted as renderer input.

## Compatibility evidence

`pnpm --filter @financial-slides/presentation-renderer test` inspects the
generated archive and confirms that representative text, table, chart, image,
and notes parts exist as native OOXML. `pnpm --filter
@financial-slides/presentation-renderer compatibility:deck` generates the
five-slide manual test deck at
`packages/presentation-renderer/tmp/renderer-compatibility.pptx`.

The generated deck must still be opened in both PowerPoint Desktop and
PowerPoint for the web before this renderer is considered production-ready.
For each application, verify:

1. all five slides open without a repair warning;
2. text can be edited without becoming an image;
3. table cells can be edited;
4. chart data can be edited;
5. the image can be selected and replaced;
6. speaker notes appear on the first slide.

## Supported input and fallbacks

| Input | Output | Fallback |
| --- | --- | --- |
| Text and insight | Native text boxes | None |
| Metrics | Native text boxes | None |
| Tables | Native PowerPoint tables | Large tables must be split upstream |
| Bar and line charts | Native PowerPoint charts | None |
| Waterfall charts | Native bar chart | Renderer emits a warning |
| Images | Selectable raster images | Missing or remote assets fail rendering |
| Arbitrary HTML/CSS | Not accepted | Compile approved layouts to slide-spec components |
| HTML tables | Not used | Compile to the canonical table component |

This boundary avoids browser-specific layout drift and keeps the conversion
path deterministic. More HTML/CSS support should only be added for a concrete,
tested layout requirement.

## Default presentation theme

The approved `theme-corporate-default` is defined once in
`packages/presentation-harness/src/theme.js`. Both the constrained HTML
preflight compiler and the PowerPoint renderer consume these tokens. The theme
owns the safe font stack, semantic colors, typography scale, spacing, chart
palette, table treatment, and source-note treatment.

To adjust the default visual language, change the semantic token rather than
editing each layout. Keep hexadecimal colors in six-character Office format,
retain the Aptos/Arial-safe font stack, run the harness contrast tests, and
regenerate the compatibility deck. A new selectable theme requires a separately
approved theme ID and equivalent compiler, renderer, editability, and preflight
coverage; arbitrary LLM-authored CSS is not accepted.
