/* App: routing + auth guards. */

import React from "react";
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { AuthProvider, StatusProvider, ToastProvider, useAuth } from "./state";
import ChatPage from "./pages/Chat";
import LoginPage from "./pages/Login";
import HomePage from "./pages/Home";
import TasksPage from "./pages/Tasks";
import CalendarPage from "./pages/Calendar";
import MemoryPage from "./pages/Memory";
import AutomationsPage from "./pages/Automations";
import FilesPage from "./pages/Files";
import ActivityPage from "./pages/Activity";
import SecurityPage from "./pages/Security";
import IntegrationsPage from "./pages/Integrations";
import SettingsPage from "./pages/Settings";

function Protected({ children }: { children: React.ReactNode }) {
  const { user, loading } = useAuth();
  if (loading) {
    return (
      <div style={{ display: "grid", placeItems: "center", height: "100vh" }}>
        <span className="spinner" />
      </div>
    );
  }
  if (!user) return <Navigate to="/login" replace />;
  return <>{children}</>;
}

export default function App() {
  return (
    <BrowserRouter>
      <ToastProvider>
        <AuthProvider>
          <StatusProvider>
            <Routes>
              <Route path="/login" element={<LoginPage />} />
              <Route path="/chat" element={<Protected><ChatPage /></Protected>} />
              <Route path="/" element={<Protected><HomePage /></Protected>} />
              <Route path="/tasks" element={<Protected><TasksPage /></Protected>} />
              <Route path="/calendar" element={<Protected><CalendarPage /></Protected>} />
              <Route path="/memory" element={<Protected><MemoryPage /></Protected>} />
              <Route path="/automations" element={<Protected><AutomationsPage /></Protected>} />
              <Route path="/files" element={<Protected><FilesPage /></Protected>} />
              <Route path="/activity" element={<Protected><ActivityPage /></Protected>} />
              <Route path="/security" element={<Protected><SecurityPage /></Protected>} />
              <Route path="/integrations" element={<Protected><IntegrationsPage /></Protected>} />
              <Route path="/settings" element={<Protected><SettingsPage /></Protected>} />
              <Route path="*" element={<Navigate to="/" replace />} />
            </Routes>
          </StatusProvider>
        </AuthProvider>
      </ToastProvider>
    </BrowserRouter>
  );
}
