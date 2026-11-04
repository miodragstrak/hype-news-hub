import React from "react";
import { createRoot } from "react-dom/client";
import { createBrowserRouter, RouterProvider } from "react-router-dom";
import { SessionApplication } from "./SessionApplication";
import { SessionAccount } from "./session";
import { installSessionTransport } from "../services/sessionTransport";
import "../index.css";

const account = new SessionAccount();
installSessionTransport(account.request);
const router = createBrowserRouter([{ path: "*", element: <SessionApplication account={account} /> }]);
createRoot(document.getElementById("root")!).render(<React.StrictMode><RouterProvider router={router} /></React.StrictMode>);
