import { create } from "zustand";

export type InputMode = "file" | "text";

type GeneratorState = {
  inputMode: InputMode;
  sourceText: string;
  fileName: string | null;
  deckPurpose: string;
  slideCount: number;
  setInputMode: (inputMode: InputMode) => void;
  setSourceText: (sourceText: string) => void;
  setFileName: (fileName: string | null) => void;
  setDeckPurpose: (deckPurpose: string) => void;
  setSlideCount: (slideCount: number) => void;
};

export const useGeneratorStore = create<GeneratorState>((set) => ({
  inputMode: "file",
  sourceText: "",
  fileName: null,
  deckPurpose: "management-review",
  slideCount: 10,
  setInputMode: (inputMode) => set({ inputMode }),
  setSourceText: (sourceText) => set({ sourceText }),
  setFileName: (fileName) => set({ fileName }),
  setDeckPurpose: (deckPurpose) => set({ deckPurpose }),
  setSlideCount: (slideCount) => set({ slideCount }),
}));
