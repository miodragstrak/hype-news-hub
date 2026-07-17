import { Navigate, Route, Routes } from "react-router-dom";

import { AppShell } from "./components/AppShell";
import { CollectionProgressPage } from "./pages/CollectionProgressPage";
import { EditorialQueuePage } from "./pages/EditorialQueuePage";
import { PublishPage } from "./pages/PublishPage";
import { PortalPreviewPage } from "./pages/PortalPreviewPage";
import { ProcessingOverviewPage } from "./pages/ProcessingOverviewPage";
import { ReviewPage } from "./pages/ReviewPage";

function App() {
  return (
    <Routes>
      <Route element={<AppShell />}>
        <Route path="/" element={<CollectionProgressPage />} />
        <Route path="/collect" element={<CollectionProgressPage />} />
        <Route path="/process" element={<ProcessingOverviewPage />} />
        <Route path="/review" element={<EditorialQueuePage />} />
        <Route path="/review/:storyId" element={<ReviewPage />} />
        <Route path="/publish" element={<PublishPage />} />
      </Route>
      <Route path="/portal-preview/:storyId" element={<PortalPreviewPage />} />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}

export default App;
