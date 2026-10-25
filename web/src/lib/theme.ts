import { create } from "zustand";

export type Theme = "light" | "dark";
const KEY = "beamline.theme";

function initial(): Theme {
  try {
    const v = localStorage.getItem(KEY);
    if (v === "light" || v === "dark") return v;
  } catch { /* storage unavailable */ }
  try {
    if (window.matchMedia?.("(prefers-color-scheme: dark)").matches) return "dark";
  } catch { /* */ }
  return "light";
}

function apply(t: Theme) {
  document.documentElement.dataset.theme = t;
}

export const useTheme = create<{ theme: Theme; toggle: () => void }>((set, get) => {
  const t = initial();
  apply(t);
  return {
    theme: t,
    toggle: () => {
      const n: Theme = get().theme === "dark" ? "light" : "dark";
      apply(n);
      try { localStorage.setItem(KEY, n); } catch { /* */ }
      set({ theme: n });
    },
  };
});

/** three.js needs concrete colours: scene palette per theme (CSS tokens can't reach WebGL materials). */
export interface ScenePalette {
  plate: string; grid: string; hole: string; outline: string; edge: string; leader: string;
  sel: string; err: string; warn: string; hover: string;
  anod: string; steel: string; housing: string; glass: string; glassOpacity: number; coat: string; wp: string; black: string; fiber: string;
  beamCore: string | null; beamOpacity: number; darkBg: boolean;
  gizmo: { color: string; hover: string; text: string; stroke: string };
}

export const PALETTES: Record<Theme, ScenePalette> = {
  light: {
    plate: "#d5d9de", grid: "#bfc5cc", hole: "#9ba3ab", outline: "#7d858e", edge: "#2a2e33", leader: "#8b939c",
    sel: "#1f5fd1", err: "#c62828", warn: "#b26a00", hover: "#c2410c",
    anod: "#3a3f45", steel: "#b9bfc6", housing: "#e4e6e9", glass: "#cfe1ec", glassOpacity: 0.55, coat: "#d8dde2", wp: "#b9c4f0", black: "#1d2024", fiber: "#d9b44a",
    beamCore: null, beamOpacity: 1, darkBg: false,
    gizmo: { color: "#f7f8f9", hover: "#dfe7f5", text: "#3a3f45", stroke: "#8b939c" },
  },
  dark: {
    plate: "#1b1f25", grid: "#2f3640", hole: "#7c8796", outline: "#8b96a5", edge: "#c9d1db", leader: "#8b96a5",
    sel: "#4da3ff", err: "#ff6b6b", warn: "#ffc145", hover: "#ffc145",
    anod: "#262b33", steel: "#7d8794", housing: "#353c46", glass: "#7fb3d5", glassOpacity: 0.3, coat: "#9aa5b1", wp: "#6f7fd6", black: "#0e1013", fiber: "#e0bd52",
    beamCore: "#ffffff", beamOpacity: 1.35, darkBg: true,
    gizmo: { color: "#1b1f25", hover: "#24405f", text: "#f2f4f7", stroke: "#8b96a5" },
  },
};

export const usePalette = () => PALETTES[useTheme((s) => s.theme)];

import { wavelengthToColor } from "./color";
/** wavelength → colour for the active theme */
export function useWlColor() {
  const dark = useTheme((s) => s.theme === "dark");
  return (nm: number) => wavelengthToColor(nm, dark);
}
