import { useState, useEffect } from 'react';
import { useTranslation } from 'next-i18next';
import { Play, X, Check, AlertCircle, Loader2, ExternalLink, ChevronDown, ChevronUp, FileText, Table, Mail, Calendar, Presentation, HardDrive, Brain } from 'lucide-react';
import api from '../lib/api';

const PLUGIN_ICONS = {
  google_docs: FileText,
  google_sheets: Table,
  gmail: Mail,
  google_calendar: Calendar,
  google_slides: Presentation,
  google_drive: HardDrive,
};

export default function ActionProposal({ proposal, onResult, onContinuation }) {
  const { t } = useTranslation(['chat']);
  // 'checking' until the real status is fetched from the backend, so a
  // proposal re-rendered from history never shows active buttons for an
  // action that was already executed or cancelled.
  const [status, setStatus] = useState('checking');
  const [result, setResult] = useState(null);
  const [loading, setLoading] = useState(false);
  const [showDetails, setShowDetails] = useState(false);

  useEffect(() => {
    let cancelled = false;
    const syncStatus = async () => {
      if (!proposal?.execution_id) {
        setStatus('pending');
        return;
      }
      try {
        const res = await api.get(`/actions/${proposal.execution_id}`);
        if (cancelled) return;
        const backendStatus = res.data.status;
        if (backendStatus === 'pending_confirmation') {
          setStatus('pending');
        } else if (backendStatus === 'confirmed' || backendStatus === 'executing') {
          setStatus('executing');
        } else if (backendStatus === 'completed') {
          setStatus('completed');
          setResult({
            display_message: null,
            resource_url: res.data.result?.url || null,
          });
        } else if (backendStatus === 'failed') {
          setStatus('failed');
          setResult({ error_message: res.data.error_message });
        } else if (backendStatus === 'cancelled') {
          setStatus('cancelled');
        } else {
          setStatus('pending');
        }
      } catch (e) {
        if (cancelled) return;
        // If the action no longer exists, don't offer buttons; on transient
        // errors fall back to pending — the backend rejects double execution.
        if (e.response?.status === 404) {
          setStatus('cancelled');
        } else {
          setStatus('pending');
        }
      }
    };
    syncStatus();
    return () => { cancelled = true; };
  }, [proposal?.execution_id]);

  const Icon = PLUGIN_ICONS[proposal.plugin] || FileText;

  const handleConfirm = async () => {
    setLoading(true);
    setStatus('executing');
    try {
      const res = await api.post(`/actions/${proposal.execution_id}/confirm`);
      setStatus(res.data.status);
      setResult(res.data);
      if (onResult) onResult(res.data);
      // If the agent continued after this action, propagate
      if (res.data.continuation && onContinuation) {
        onContinuation(res.data.continuation);
      }
    } catch (e) {
      setStatus('failed');
      setResult({ error_message: e.response?.data?.detail || e.response?.data?.message || 'Execution failed' });
    } finally {
      setLoading(false);
    }
  };

  const handleCancel = async () => {
    try {
      const res = await api.post(`/actions/${proposal.execution_id}/cancel`);
      setStatus('cancelled');
      if (res.data.continuation && onContinuation) {
        onContinuation(res.data.continuation);
      }
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
        {/* Agent thought */}
        {proposal.thought && (
          <div className="flex items-start gap-2 mb-2 text-sm text-gray-600 italic">
            <Brain className="w-4 h-4 mt-0.5 shrink-0 text-gray-400" />
            <span>{proposal.thought}</span>
          </div>
        )}

        {/* Human-readable summary */}
        <p className="text-sm text-gray-800 mb-1">{proposal.display_summary}</p>

        {/* Expandable details */}
        {proposal.params && (
          <>
            <button
              onClick={() => setShowDetails(!showDetails)}
              className="text-xs text-gray-500 hover:text-gray-700 flex items-center gap-1 mb-2"
            >
              {showDetails ? <ChevronUp className="w-3 h-3" /> : <ChevronDown className="w-3 h-3" />}
              {showDetails ? 'Masquer les details' : 'Voir les details'}
            </button>
            {showDetails && (
              <pre className="text-xs bg-white border rounded p-2 mb-2 overflow-x-auto">
                {JSON.stringify(proposal.params, null, 2)}
              </pre>
            )}
          </>
        )}

        {/* Status check in progress: no actionable buttons until verified */}
        {status === 'checking' && (
          <div className="flex items-center mt-3 text-sm text-gray-400">
            <Loader2 className="w-4 h-4 mr-1 animate-spin" />
          </div>
        )}

        {/* Action buttons */}
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
              <a href={result.resource_url} target="_blank" rel="noopener noreferrer"
                className="inline-flex items-center mt-2 text-sm text-blue-600 hover:underline">
                <ExternalLink className="w-3 h-3 mr-1" /> {t('chat:messages.openButton')}
              </a>
            )}
          </div>
        )}

        {status === 'failed' && (
          <div className="mt-3 p-3 bg-red-50 rounded-button border border-red-200">
            <div className="flex items-center text-sm text-red-700">
              <AlertCircle className="w-4 h-4 mr-1" /> {t('chat:actions.failed')}
            </div>
            {result?.error_message && (
              <p className="text-sm text-red-600 mt-1">{result.error_message}</p>
            )}
          </div>
        )}

        {status === 'cancelled' && (
          <div className="mt-3 flex items-center text-sm text-gray-500">
            <X className="w-4 h-4 mr-1" /> {t('chat:actions.cancelled')}
          </div>
        )}
      </div>
    </div>
  );
}
