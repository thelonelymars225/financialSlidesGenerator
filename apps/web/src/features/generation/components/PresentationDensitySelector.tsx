import {
  PRESENTATION_DENSITY_OPTIONS,
  type PresentationDensity,
} from "../density";

export function PresentationDensitySelector({
  value,
  onChange,
  disabled = false,
}: {
  value: PresentationDensity;
  onChange: (value: PresentationDensity) => void;
  disabled?: boolean;
}) {
  return (
    <fieldset className="mt-5" disabled={disabled}>
      <legend className="text-sm font-medium text-stone-600 dark:text-stone-300">
        Presentation detail
      </legend>
      <p className="mt-1 text-xs text-stone-500 dark:text-stone-400" id="density-help">
        Controls detail within each slide. Slide count, source grounding, and factual accuracy stay the same.
      </p>
      <div className="mt-3 grid gap-2 sm:grid-cols-3" aria-describedby="density-help">
        {PRESENTATION_DENSITY_OPTIONS.map((option) => (
          <label
            className={`cursor-pointer rounded-xl border p-3 transition focus-within:outline-2 focus-within:outline-offset-2 focus-within:outline-emerald-700 ${
              value === option.value
                ? "border-emerald-800 bg-emerald-50 dark:border-emerald-300 dark:bg-emerald-950/30"
                : "border-stone-200 bg-stone-50 hover:border-stone-300 dark:border-white/10 dark:bg-white/5"
            }`}
            key={option.value}
          >
            <input
              checked={value === option.value}
              className="mr-2 accent-emerald-800"
              disabled={disabled}
              name="presentation-density"
              onChange={() => onChange(option.value)}
              type="radio"
              value={option.value}
            />
            <strong className="text-sm">{option.label}</strong>
            <span className="mt-1 block text-xs font-semibold text-emerald-800 dark:text-emerald-300">
              {option.summary}
            </span>
            <span className="mt-1 block text-xs leading-5 text-stone-500 dark:text-stone-400">
              {option.detail}
            </span>
          </label>
        ))}
      </div>
    </fieldset>
  );
}
