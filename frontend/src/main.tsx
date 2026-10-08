import "./design-system/theme.css";
import React from "react";
import { createRoot } from "react-dom/client";
import { Provider } from "jotai";
import App from "./app/App";

createRoot(document.getElementById("root")!).render(
  <React.StrictMode><Provider><App /></Provider></React.StrictMode>,
);
