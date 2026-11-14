import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { SWRConfig } from "swr";
import "./index.css";
import App from "./App.tsx";
import { SWR_OPTIONS } from "./lib/queries";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <SWRConfig value={SWR_OPTIONS}>
      <App />
    </SWRConfig>
  </StrictMode>,
);
