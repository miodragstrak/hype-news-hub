import { Navigate, Route, Routes } from "react-router-dom";

import { AppShell } from "./components/AppShell";
import { CollectionProgressPage } from "./pages/CollectionProgressPage";
import { DashboardPage } from "./pages/DashboardPage";
import { EditorialQueuePage } from "./pages/EditorialQueuePage";
import { PublishPage } from "./pages/PublishPage";
import { ProcessingOverviewPage } from "./pages/ProcessingOverviewPage";
import { ReviewPage } from "./pages/ReviewPage";

function App() {
  return (
    <Routes>
      <Route element={<AppShell />}>
        <Route path="/" element={<DashboardPage />} />
        <Route path="/collect" element={<CollectionProgressPage />} />
        <Route path="/process" element={<ProcessingOverviewPage />} />
        <Route path="/review" element={<EditorialQueuePage />} />
        <Route path="/review/:articleId" element={<ReviewPage />} />
        <Route path="/publish" element={<PublishPage />} />
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}

export default App;
