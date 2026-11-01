import { Navigate, Route, Routes } from "react-router-dom";

import { AppShell } from "./components/AppShell";
import { CollectionProgressPage } from "./pages/CollectionProgressPage";
import { EditorialQueuePage } from "./pages/EditorialQueuePage";
import { PublishPage } from "./pages/PublishPage";
import { PortalPreviewPage } from "./pages/PortalPreviewPage";
import { ProcessingOverviewPage } from "./pages/ProcessingOverviewPage";
import { ReviewPage } from "./pages/ReviewPage";
import { EditorialDraftPage } from "./pages/EditorialDraftPage";
import { EditorialHistoryPage } from "./pages/EditorialHistoryPage";
import { EditorialDecisionsPage } from "./pages/EditorialDecisionsPage";
import { EditorialApprovedPage } from "./pages/EditorialApprovedPage";
import { EditorialAccessProvider, type EditorialIdentityAdapter } from "./context/EditorialAccessContext";

function App({ editorialIdentity }: { editorialIdentity?: EditorialIdentityAdapter }) {
  return (
    <EditorialAccessProvider identity={editorialIdentity}>
    <Routes>
      <Route element={<AppShell />}>
        <Route path="/" element={<CollectionProgressPage />} />
        <Route path="/collect" element={<CollectionProgressPage />} />
        <Route path="/process" element={<ProcessingOverviewPage />} />
        <Route path="/review" element={<EditorialQueuePage />} />
        <Route path="/review/:storyId" element={<ReviewPage />} />
        <Route path="/review/:storyId/edit" element={<EditorialDraftPage />} />
        <Route path="/review/:storyId/history" element={<EditorialHistoryPage />} />
        <Route path="/review/:storyId/decisions" element={<EditorialDecisionsPage />} />
        <Route path="/review/:storyId/approved" element={<EditorialApprovedPage />} />
        <Route path="/publish" element={<PublishPage />} />
      </Route>
      <Route path="/portal-preview/:storyId" element={<PortalPreviewPage />} />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
    </EditorialAccessProvider>
  );
}

export default App;
