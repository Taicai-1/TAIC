import { useState, useEffect } from 'react';
import { useTranslation } from 'next-i18next';
import { FileText, Table, Mail, Calendar, Presentation, HardDrive, Check, ExternalLink } from 'lucide-react';
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

  const togglePlugin = (pluginName) => {
    const current = enabledPlugins || [];
    const updated = current.includes(pluginName)
      ? current.filter(p => p !== pluginName)
      : [...current, pluginName];
    onChange(updated);
  };

  const connectGoogle = async () => {
    const allScopes = plugins
      .filter(p => (enabledPlugins || []).includes(p.name))
      .flatMap(p => p.required_scopes);
    const uniqueScopes = [...new Set(allScopes)];

    try {
      const res = await api.get(`/auth/google/authorize?scopes=${uniqueScopes.join(',')}`);
      window.open(res.data.authorization_url, '_blank', 'width=600,height=700');
    } catch (e) {
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
        {googleStatus.connected ? (
          <span className="inline-flex items-center px-2 py-1 text-xs font-medium text-green-700 bg-green-100 rounded-full">
            <Check className="w-3 h-3 mr-1" />
            {t('agents:form.plugins.googleConnected')}
          </span>
        ) : (
          <button
            type="button"
            onClick={connectGoogle}
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

          return (
            <button
              key={plugin.name}
              type="button"
              onClick={() => togglePlugin(plugin.name)}
              className={`flex items-center p-3 rounded-card border-2 transition-all text-left ${
                isEnabled
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
              </div>
              {isEnabled && (
                <Check className="w-5 h-5 text-primary-600 flex-shrink-0 ml-2" />
              )}
            </button>
          );
        })}
      </div>
    </div>
  );
}
