import { useState, useEffect, useCallback } from 'react';
import { BrowserRouter, Routes, Route } from 'react-router-dom';
import { Layout } from './components';
import { HomePage, TasksPage, TaskDetailPage, AgentsPage, ChannelsPage, LoginPage, ChatPage, ModelConfigPage, AgentSettingsPage, SystemConfigPage, ConsolePage, SkillsPage } from './pages';
import { api } from './services/api';

function App() {
  const [isAuthenticated, setIsAuthenticated] = useState<boolean | null>(null);
  const [authError, setAuthError] = useState<string | null>(null);

  // Check authentication on mount
  useEffect(() => {
    const checkAuth = async () => {
      const isValid = await api.verifyApiKey();
      setIsAuthenticated(isValid);
    };
    checkAuth();

    // Listen for unauthorized events
    const handleUnauthorized = () => {
      setIsAuthenticated(false);
      setAuthError('Session expired. Please sign in again.');
    };
    window.addEventListener('auth:unauthorized', handleUnauthorized);

    return () => {
      window.removeEventListener('auth:unauthorized', handleUnauthorized);
    };
  }, []);

  const handleLogin = useCallback(async (apiKey: string) => {
    setAuthError(null);
    api.setApiKey(apiKey);
    const isValid = await api.verifyApiKey();
    if (isValid) {
      setIsAuthenticated(true);
    } else {
      api.setApiKey(null);
      setAuthError('Invalid API key. Please try again.');
      setIsAuthenticated(false);
    }
  }, []);

  // Loading state
  if (isAuthenticated === null) {
    return (
      <div className="min-h-screen bg-gray-50 flex items-center justify-center">
        <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-600"></div>
      </div>
    );
  }

  // Not authenticated - show login page
  if (!isAuthenticated) {
    return <LoginPage onLogin={handleLogin} error={authError || undefined} />;
  }

  // Authenticated - show main app
  return (
    <BrowserRouter>
      <Layout>
        <Routes>
          <Route path="/" element={<HomePage />} />
          <Route path="/tasks" element={<TasksPage />} />
          <Route path="/tasks/:id" element={<TaskDetailPage />} />
          <Route path="/agents" element={<AgentsPage />} />
          <Route path="/channels" element={<ChannelsPage />} />
          <Route path="/models" element={<ModelConfigPage />} />
          <Route path="/agent-settings" element={<AgentSettingsPage />} />
          <Route path="/system" element={<SystemConfigPage />} />
          <Route path="/chat" element={<ChatPage />} />
          <Route path="/console" element={<ConsolePage />} />
          <Route path="/skills" element={<SkillsPage />} />
        </Routes>
      </Layout>
    </BrowserRouter>
  );
}

export default App;
