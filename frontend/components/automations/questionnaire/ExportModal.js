import { useState, useEffect } from 'react';
import { useTranslation } from 'next-i18next';
import toast from 'react-hot-toast';
import { X, Upload } from 'lucide-react';
import api from '../../../lib/api';
import { EXPORTABLE_AGENT_TYPES } from './constants';

export default function ExportModal({ questionnaireId, responseIds, onClose, onExported }) {
  const { t } = useTranslation('automations');
  const [agents, setAgents] = useState([]);
  const [targetAgentId, setTargetAgentId] = useState('');
  const [exporting, setExporting] = useState(false);

  useEffect(() => {
    api
      .get('/agents')
      .then((res) =>
        setAgents(
          (res.data.agents || []).filter((a) => EXPORTABLE_AGENT_TYPES.includes(a.type))
        )
      )
      .catch(() => setAgents([]));
  }, []);

  const doExport = async () => {
    setExporting(true);
    try {
      const res = await api.post(`/api/automations/questionnaires/${questionnaireId}/export`, {
        response_ids: responseIds,
        target_agent_id: parseInt(targetAgentId, 10),
      });
      toast.success(t('export.success', { count: res.data.exported }));
      if (res.data.failed_response_ids?.length) {
        toast.error(t('export.partialFail', { count: res.data.failed_response_ids.length }));
      }
      onExported?.();
      onClose();
    } catch {
      toast.error(t('export.error'));
    } finally {
      setExporting(false);
    }
  };

  return (
    <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50 p-4">
      <div className="bg-white rounded-card shadow-lg w-full max-w-md p-6">
        <div className="flex items-center justify-between mb-2">
          <h3 className="text-base font-bold text-gray-900">{t('export.title')}</h3>
          <button onClick={onClose} className="p-1 text-gray-400 hover:text-gray-600">
            <X className="w-4 h-4" />
          </button>
        </div>
        <p className="text-sm text-gray-500 mb-4">{t('export.description')}</p>

        <label className="block text-sm font-medium text-gray-700 mb-1.5">
          {t('export.targetLabel')}
        </label>
        <select
          value={targetAgentId}
          onChange={(e) => setTargetAgentId(e.target.value)}
          className="w-full px-3 py-2 border border-gray-200 rounded-input text-sm bg-white focus:ring-2 focus:ring-primary-500 mb-6"
        >
          <option value="">{t('export.selectAgent')}</option>
          {agents.map((a) => (
            <option key={a.id} value={a.id}>
              {a.name}
            </option>
          ))}
        </select>

        <div className="flex items-center justify-end gap-3">
          <button
            onClick={onClose}
            className="px-4 py-2 text-sm font-medium text-gray-600 hover:text-gray-800"
          >
            {t('export.cancel')}
          </button>
          <button
            onClick={doExport}
            disabled={exporting || !targetAgentId}
            className="flex items-center gap-2 px-4 py-2 bg-primary-600 text-white text-sm font-semibold rounded-button hover:bg-primary-700 transition-colors disabled:opacity-50"
          >
            <Upload className="w-4 h-4" />
            {t('export.confirm', { count: responseIds.length })}
          </button>
        </div>
      </div>
    </div>
  );
}
