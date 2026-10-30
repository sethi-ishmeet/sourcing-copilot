import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter, Route, Routes } from "react-router-dom";
import App from "./App";
import RolePage from "./pages/RolePage";
import ScreeningPage from "./pages/ScreeningPage";
import "./index.css";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <BrowserRouter>
      <Routes>
        <Route element={<App />}>
          <Route index element={<RolePage />} />
          <Route path="screenings/:runId" element={<ScreeningPage />} />
        </Route>
      </Routes>
    </BrowserRouter>
  </StrictMode>,
);
