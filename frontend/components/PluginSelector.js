import { useState, useEffect } from 'react';
import { useTranslation } from 'next-i18next';
import toast from 'react-hot-toast';
import { FileText, Table, Mail, Calendar, Presentation, HardDrive, Check, ExternalLink, AlertTriangle } from 'lucide-react';
import api from '../lib/api';

const PLUGIN_ICONS = {
  google_docs: FileText,
  google_sheets: Table,
  gmail: Mail,
  google_calendar: Calendar,
  google_slides: Presentation,
  google_drive: HardDrive,
};

export default function PluginSelector({ enabledPlugins, onChange }) {
  const { t } = useTranslation(['agents']);
  const [plugins, setPlugins] = useState([]);
  const [googleStatus, setGoogleStatus] = useState({ connected: false, granted_scopes: [] });
  const [loading, setLoading] = useState(true);

  const refreshGoogleStatus = async () => {
    try {
      const res = await api.get('/auth/google/status');
      setGoogleStatus(res.data);
    } catch (e) {
      console.error('Failed to refresh Google status:', e);
    }
  };

  useEffect(() => {
    async function load() {
      try {
        const [pluginsRes, statusRes] = await Promise.all([
          api.get('/plugins'),
          api.get('/auth/google/status'),
        ]);
        setPlugins(pluginsRes.data.plugins || []);
        setGoogleStatus(statusRes.data);
      } catch (e) {
        console.error('Failed to load plugins:', e);
      } finally {
        setLoading(false);
      }
    }
    load();
  }, []);

  // Re-check Google status when window regains focus (after OAuth popup)
  useEffect(() => {
    const onFocus = () => refreshGoogleStatus();
    window.addEventListener('focus', onFocus);
    return () => window.removeEventListener('focus', onFocus);
  }, []);

  // Re-check Google status via localStorage event (cross-tab communication from OAuth popup)
  useEffect(() => {
    const onStorage = (e) => {
      if (e.key === 'google_oauth_done') refreshGoogleStatus();
    };
    window.addEventListener('storage', onStorage);
    return () => window.removeEventListener('storage', onStorage);
  }, []);

  const togglePlugin = (pluginName) => {
    const current = enabledPlugins || [];
    const updated = current.includes(pluginName)
      ? current.filter(p => p !== pluginName)
      : [...current, pluginName];
    onChange(updated);
  };

  // Compute missing scopes for enabled plugins
  const getMissingScopes = () => {
    const granted = new Set(googleStatus.granted_scopes || []);
    const needed = new Set();
    (enabledPlugins || []).forEach(pluginName => {
      const plugin = plugins.find(p => p.name === pluginName);
      if (plugin) {
        (plugin.required_scopes || []).forEach(s => {
          if (!granted.has(s)) needed.add(s);
        });
      }
    });
    return [...needed];
  };

  const missingScopes = googleStatus.connected ? getMissingScopes() : [];

  const connectGoogle = async (scopeOverrides) => {
    // Collect scopes: use overrides if provided, otherwise all enabled/all plugins
    let uniqueScopes;
    if (scopeOverrides && scopeOverrides.length > 0) {
      // When reconnecting for missing scopes, include all currently needed scopes
      const selectedPlugins = plugins.filter(p => (enabledPlugins || []).includes(p.name));
      const allScopes = selectedPlugins.flatMap(p => p.required_scopes);
      uniqueScopes = [...new Set(allScopes)];
    } else {
      const selectedPlugins = (enabledPlugins || []).length > 0
        ? plugins.filter(p => enabledPlugins.includes(p.name))
        : plugins;
      const allScopes = selectedPlugins.flatMap(p => p.required_scopes);
      uniqueScopes = [...new Set(allScopes)];
    }

    if (uniqueScopes.length === 0) return;

    // Open popup immediately (before await) to avoid browser popup blocker
    const popup = window.open('about:blank', '_blank', 'width=600,height=700');

    try {
      const res = await api.get(`/auth/google/authorize?scopes=${uniqueScopes.join(',')}`);
      if (popup) {
        popup.location.href = res.data.authorization_url;
      } else {
        window.location.href = res.data.authorization_url;
      }
    } catch (e) {
      if (popup) popup.close();
      const detail = e.response?.data?.detail || e.response?.data?.message || '';
      if (detail.includes('not configured')) {
        toast.error(t('agents:form.plugins.googleNotConfigured', 'Google OAuth is not configured on the server.'));
      } else {
        toast.error(t('agents:form.plugins.googleAuthError', 'Failed to connect Google account.'));
      }
      console.error('Failed to start Google auth:', e);
    }
  };

  if (loading) {
    return <div className="animate-pulse h-32 bg-gray-100 rounded-card" />;
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <label className="text-sm font-medium text-gray-700">
          {t('agents:form.plugins.label')}
        </label>
        {googleStatus.connected && missingScopes.length === 0 ? (
          <span className="inline-flex items-center px-2 py-1 text-xs font-medium text-green-700 bg-green-100 rounded-full">
            <Check className="w-3 h-3 mr-1" />
            {t('agents:form.plugins.googleConnected')}
          </span>
        ) : googleStatus.connected && missingScopes.length > 0 ? (
          <button
            type="button"
            onClick={() => connectGoogle(missingScopes)}
            className="inline-flex items-center px-3 py-1.5 text-xs font-medium text-white bg-amber-600 rounded-button hover:bg-amber-700 transition-colors"
          >
            <AlertTriangle className="w-3 h-3 mr-1" />
            {t('agents:form.plugins.reconnectGoogle', 'Update permissions')}
          </button>
        ) : (
          <button
            type="button"
            onClick={() => connectGoogle()}
            className="inline-flex items-center px-3 py-1.5 text-xs font-medium text-white bg-blue-600 rounded-button hover:bg-blue-700 transition-colors"
          >
            <ExternalLink className="w-3 h-3 mr-1" />
            {t('agents:form.plugins.connectGoogle')}
          </button>
        )}
      </div>

      <p className="text-xs text-gray-500">{t('agents:form.plugins.description')}</p>

      <div className="grid grid-cols-2 gap-3">
        {plugins.map(plugin => {
          const Icon = PLUGIN_ICONS[plugin.name] || FileText;
          const isEnabled = (enabledPlugins || []).includes(plugin.name);
          const granted = new Set(googleStatus.granted_scopes || []);
          const pluginMissing = isEnabled && (plugin.required_scopes || []).some(s => !granted.has(s));

          return (
            <button
              key={plugin.name}
              type="button"
              onClick={() => togglePlugin(plugin.name)}
              className={`flex items-center p-3 rounded-card border-2 transition-all text-left ${
                isEnabled && pluginMissing
                  ? 'border-amber-400 bg-amber-50 shadow-sm'
                  : isEnabled
                  ? 'border-primary-500 bg-primary-50 shadow-sm'
                  : 'border-gray-200 bg-white hover:border-gray-300'
              }`}
            >
              <div className={`p-2 rounded-button mr-3 ${isEnabled ? 'bg-primary-100' : 'bg-gray-100'}`}>
                <Icon className={`w-5 h-5 ${isEnabled ? 'text-primary-600' : 'text-gray-500'}`} />
              </div>
              <div className="flex-1 min-w-0">
                <div className="text-sm font-medium text-gray-900">{plugin.display_name}</div>
                <div className="text-xs text-gray-500 truncate">{plugin.description}</div>
                {pluginMissing && (
                  <div className="text-xs text-amber-600 mt-0.5">{t('agents:form.plugins.scopesMissing', 'Permissions required')}</div>
                )}
              </div>
              {isEnabled && !pluginMissing && (
                <Check className="w-5 h-5 text-primary-600 flex-shrink-0 ml-2" />
              )}
              {pluginMissing && (
                <AlertTriangle className="w-5 h-5 text-amber-500 flex-shrink-0 ml-2" />
              )}
            </button>
          );
        })}
      </div>
    </div>
  );
}
