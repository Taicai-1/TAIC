import { useState } from 'react';
import { useTranslation } from 'next-i18next';
import { Play, X, Check, AlertCircle, Loader2, ExternalLink, FileText, Table, Mail, Calendar, Presentation, HardDrive } from 'lucide-react';
import api from '../lib/api';

const PLUGIN_ICONS = {
  google_docs: FileText,
  google_sheets: Table,
  gmail: Mail,
  google_calendar: Calendar,
  google_slides: Presentation,
  google_drive: HardDrive,
};

export default function ActionProposal({ proposal, onResult }) {
  const { t } = useTranslation(['chat']);
  const [status, setStatus] = useState('pending');
  const [result, setResult] = useState(null);
  const [loading, setLoading] = useState(false);

  const Icon = PLUGIN_ICONS[proposal.plugin] || FileText;

  const handleConfirm = async () => {
    setLoading(true);
    setStatus('executing');
    try {
      const res = await api.post(`/actions/${proposal.execution_id}/confirm`);
      setStatus(res.data.status);
      setResult(res.data);
      if (onResult) onResult(res.data);
    } catch (e) {
      setStatus('failed');
      setResult({ error_message: e.response?.data?.detail || 'Execution failed' });
    } finally {
      setLoading(false);
    }
  };

  const handleCancel = async () => {
    try {
      await api.post(`/actions/${proposal.execution_id}/cancel`);
      setStatus('cancelled');
    } catch (e) {
      console.error('Failed to cancel action:', e);
    }
  };

  return (
    <div className="mt-3 border border-gray-200 rounded-card overflow-hidden bg-gray-50">
      {/* Header */}
      <div className="flex items-center px-4 py-2 bg-gray-100 border-b border-gray-200">
        <Icon className="w-4 h-4 text-gray-600 mr-2" />
        <span className="text-sm font-medium text-gray-700">{t('chat:actions.actionProposed')}</span>
      </div>

      {/* Body */}
      <div className="px-4 py-3">
        <p className="text-sm text-gray-800 mb-2">{proposal.display_summary}</p>

        {/* Action buttons — only show when pending */}
        {status === 'pending' && (
          <div className="flex gap-2 mt-3">
            <button
              onClick={handleConfirm}
              disabled={loading}
              className="inline-flex items-center px-4 py-2 text-sm font-medium text-white bg-green-600 rounded-button hover:bg-green-700 transition-colors disabled:opacity-50"
            >
              {loading ? <Loader2 className="w-4 h-4 mr-1 animate-spin" /> : <Play className="w-4 h-4 mr-1" />}
              {t('chat:actions.confirm')}
            </button>
            <button
              onClick={handleCancel}
              disabled={loading}
              className="inline-flex items-center px-4 py-2 text-sm font-medium text-gray-700 bg-gray-200 rounded-button hover:bg-gray-300 transition-colors disabled:opacity-50"
            >
              <X className="w-4 h-4 mr-1" />
              {t('chat:actions.cancel')}
            </button>
          </div>
        )}

        {/* Status badges */}
        {status === 'executing' && (
          <div className="flex items-center mt-3 text-sm text-blue-600">
            <Loader2 className="w-4 h-4 mr-1 animate-spin" />
            {t('chat:actions.executing')}
          </div>
        )}

        {status === 'completed' && result && (
          <div className="mt-3 p-3 bg-green-50 rounded-button border border-green-200">
            <div className="flex items-center text-sm text-green-700">
              <Check className="w-4 h-4 mr-1" />
              {t('chat:actions.completed')}
            </div>
            {result.display_message && (
              <p className="text-sm text-green-800 mt-1">{result.display_message}</p>
            )}
            {result.resource_url && (
              <a
                href={result.resource_url}
                target="_blank"
                rel="noopener noreferrer"
                className="inline-flex items-center mt-2 text-sm text-blue-600 hover:underline"
              >
                <ExternalLink className="w-3 h-3 mr-1" />
                {t('chat:messages.openButton')}
              </a>
            )}
          </div>
        )}

        {status === 'failed' && (
          <div className="mt-3 p-3 bg-red-50 rounded-button border border-red-200">
            <div className="flex items-center text-sm text-red-700">
              <AlertCircle className="w-4 h-4 mr-1" />
              {t('chat:actions.failed')}
            </div>
            {result?.error_message && (
              <p className="text-sm text-red-600 mt-1">{result.error_message}</p>
            )}
          </div>
        )}

        {status === 'cancelled' && (
          <div className="mt-3 flex items-center text-sm text-gray-500">
            <X className="w-4 h-4 mr-1" />
            {t('chat:actions.cancelled')}
          </div>
        )}
      </div>
    </div>
  );
}
