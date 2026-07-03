import React from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter } from "react-router-dom";

import App from "./App";
import { DemoDataProvider } from "./context/DemoDataContext";
import "./index.css";

ReactDOM.createRoot(document.getElementById("root") as HTMLElement).render(
  <React.StrictMode>
    <DemoDataProvider>
      <BrowserRouter>
        <App />
      </BrowserRouter>
    </DemoDataProvider>
  </React.StrictMode>,
);
