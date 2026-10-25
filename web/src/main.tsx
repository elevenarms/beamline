import { StrictMode, type ComponentType } from "react";
import { createRoot } from "react-dom/client";
import "@fontsource/ibm-plex-sans/400.css";
import "@fontsource/ibm-plex-sans/500.css";
import "@fontsource/ibm-plex-sans/600.css";
import "@fontsource/ibm-plex-mono/400.css";
import Preview from "./Preview";

// Use the full App once it exists; until then show the minimal Preview so the viewer is never blank.
const apps = import.meta.glob<{ default: ComponentType }>("./App.tsx", { eager: true });
const Root = apps["./App.tsx"]?.default ?? Preview;

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <Root />
  </StrictMode>,
);
