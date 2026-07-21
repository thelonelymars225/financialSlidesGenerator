import { create } from "zustand";

export type InputMode = "file" | "text";
export type Theme = "light" | "dark";

function getInitialTheme(): Theme {
  if (typeof window === "undefined") return "light";

  const savedTheme = window.localStorage.getItem("financial-slides-theme");
  if (savedTheme === "light" || savedTheme === "dark") return savedTheme;

  return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

type GeneratorState = {
  theme: Theme;
  inputMode: InputMode;
  sourceText: string;
  fileName: string | null;
  deckPurpose: string;
  slideCount: number;
  toggleTheme: () => void;
  setInputMode: (inputMode: InputMode) => void;
  setSourceText: (sourceText: string) => void;
  setFileName: (fileName: string | null) => void;
  setDeckPurpose: (deckPurpose: string) => void;
  setSlideCount: (slideCount: number) => void;
};

export const useGeneratorStore = create<GeneratorState>((set) => ({
  theme: getInitialTheme(),
  inputMode: "file",
  sourceText: "",
  fileName: null,
  deckPurpose: "management-review",
  slideCount: 10,
  toggleTheme: () => set((state) => ({ theme: state.theme === "light" ? "dark" : "light" })),
  setInputMode: (inputMode) => set({ inputMode }),
  setSourceText: (sourceText) => set({ sourceText }),
  setFileName: (fileName) => set({ fileName }),
  setDeckPurpose: (deckPurpose) => set({ deckPurpose }),
  setSlideCount: (slideCount) => set({ slideCount }),
}));
