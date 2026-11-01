import React from "react";
import ReactDOM from "react-dom/client";
import { createBrowserRouter, RouterProvider } from "react-router-dom";

import App from "./App";
import { DemoDataProvider } from "./context/DemoDataContext";
import "./index.css";

// Data-router navigation lets the editor block links and browser Back on unsaved changes.
const router = createBrowserRouter([{ path: "*", element: <App /> }]);

ReactDOM.createRoot(document.getElementById("root") as HTMLElement).render(
  <React.StrictMode>
    <DemoDataProvider>
      <RouterProvider router={router} />
    </DemoDataProvider>
  </React.StrictMode>,
);
