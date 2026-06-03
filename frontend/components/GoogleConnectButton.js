import { useState, useEffect } from 'react';
import { useTranslation } from 'next-i18next';
import { ExternalLink, Check } from 'lucide-react';
import api from '../lib/api';

export default function GoogleConnectButton({ requiredScopes = [] }) {
  const { t } = useTranslation(['agents']);
  const [status, setStatus] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    api.get('/auth/google/status')
      .then(res => setStatus(res.data))
      .catch(() => setStatus({ connected: false, granted_scopes: [] }))
      .finally(() => setLoading(false));
  }, []);

  const handleConnect = async () => {
    const scopes = requiredScopes.length > 0 ? requiredScopes : [];
    try {
      const res = await api.get(`/auth/google/authorize?scopes=${scopes.join(',')}`);
      window.open(res.data.authorization_url, '_blank', 'width=600,height=700');
    } catch (e) {
      console.error('Failed to start Google auth:', e);
    }
  };

  if (loading) return null;

  if (status?.connected) {
    return (
      <span className="inline-flex items-center px-2 py-1 text-xs font-medium text-green-700 bg-green-100 rounded-full">
        <Check className="w-3 h-3 mr-1" />
        {t('agents:form.plugins.googleConnected')}
      </span>
    );
  }

  return (
    <button
      type="button"
      onClick={handleConnect}
      className="inline-flex items-center px-3 py-1.5 text-xs font-medium text-white bg-blue-600 rounded-button hover:bg-blue-700 transition-colors"
    >
      <ExternalLink className="w-3 h-3 mr-1" />
      {t('agents:form.plugins.connectGoogle')}
    </button>
  );
}
