import React from "react";
import ReactDOM from "react-dom/client";

import { App } from "./App";
import "./styles.css";


/** Mount the React frontend into the browser document. */
function renderApplication(): void {
  ReactDOM.createRoot(document.getElementById("root")!).render(<App />);
}


renderApplication();