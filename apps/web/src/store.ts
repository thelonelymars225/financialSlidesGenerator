import { create } from "zustand";

export type Theme = "light" | "dark";

function getInitialTheme(): Theme {
  if (typeof window === "undefined") return "light";

  const savedTheme = window.localStorage.getItem("financial-slides-theme");
  if (savedTheme === "light" || savedTheme === "dark") return savedTheme;

  return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

type GeneratorState = {
  theme: Theme;
  toggleTheme: () => void;
};

export const useGeneratorStore = create<GeneratorState>((set) => ({
  theme: getInitialTheme(),
  toggleTheme: () => set((state) => ({ theme: state.theme === "light" ? "dark" : "light" })),
}));
