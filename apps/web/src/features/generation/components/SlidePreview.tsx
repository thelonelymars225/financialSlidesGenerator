import type { GenerationResult, SlideComponent } from "../types";

function componentText(component: SlideComponent): string {
  return component.text
    ?? component.statement
    ?? component.value?.displayedValue
    ?? String(component.value?.value ?? "");
}

export function SlidePreview({ result }: { result: GenerationResult }) {
  return (
    <section className="mt-6" aria-labelledby="slide-preview-title">
      <div className="mb-3 flex items-end justify-between gap-4">
        <div>
          <p className="text-xs font-bold uppercase tracking-[0.18em] text-orange-700">Preview</p>
          <h3 id="slide-preview-title" className="text-xl font-bold">{result.slide_spec.title}</h3>
        </div>
        <span className="text-sm text-stone-500">{result.slide_spec.slides.length} slides</span>
      </div>
      <div className="grid gap-4 md:grid-cols-2">
        {result.slide_spec.slides.map((slide) => (
          <article
            className="aspect-video overflow-hidden rounded-xl border border-stone-200 bg-stone-50 p-4 shadow-sm dark:border-white/10 dark:bg-black/20"
            key={slide.id}
          >
            <p className="text-xs font-semibold text-stone-400">Slide {slide.order}</p>
            <h4 className="mt-1 font-bold text-emerald-950 dark:text-emerald-100">{slide.title}</h4>
            <div className="mt-4 space-y-2">
              {slide.components.map((component) => (
                <div key={component.id}>
                  {component.label && <p className="text-xs font-medium text-stone-500">{component.label}</p>}
                  <p className="line-clamp-4 text-sm">{componentText(component)}</p>
                </div>
              ))}
            </div>
          </article>
        ))}
      </div>
    </section>
  );
}
