import { useState, useEffect } from 'react';
import { useTranslation } from 'next-i18next';
import { X, Upload, Loader2 } from 'lucide-react';
import api from '../../lib/api';
import toast from 'react-hot-toast';

export default function ExportModal({ agentId, responseIds, onClose }) {
  const { t } = useTranslation('questionnaire');
  const [agents, setAgents] = useState([]);
  const [targetAgentId, setTargetAgentId] = useState(null);
  const [exporting, setExporting] = useState(false);

  useEffect(() => {
    loadAgents();
  }, []);

  const loadAgents = async () => {
    try {
      const res = await api.get('/api/agents');
      const ragAgents = (res.data || []).filter(
        (a) => (a.type === 'conversationnel' || a.type === 'actionnable') && a.id !== agentId
      );
      setAgents(ragAgents);
      if (ragAgents.length > 0) setTargetAgentId(ragAgents[0].id);
    } catch (err) {
      console.error('Failed to load agents:', err);
    }
  };

  const handleExport = async () => {
    if (!targetAgentId) return;
    setExporting(true);
    try {
      const res = await api.post(`/api/agents/${agentId}/responses/export`, {
        response_ids: responseIds,
        target_agent_id: targetAgentId,
      });
      toast.success(t('responses.exportSuccess', { count: res.data.exported }));
      onClose();
    } catch (err) {
      toast.error('Export failed');
    } finally {
      setExporting(false);
    }
  };

  return (
    <div className="fixed inset-0 bg-black/50 backdrop-blur-sm flex items-center justify-center p-4 z-50 animate-fade-in">
      <div className="bg-white rounded-card shadow-floating max-w-md w-full animate-scale-in">
        <div className="px-6 py-4 border-b border-gray-100 flex items-center justify-between">
          <h3 className="text-lg font-heading font-bold text-gray-900">{t('responses.exportToAgent')}</h3>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600"><X className="w-5 h-5" /></button>
        </div>
        <div className="px-6 py-5 space-y-4">
          <p className="text-sm text-gray-600">
            {responseIds.length} réponse(s) sélectionnée(s)
          </p>
          <div>
            <label className="block text-sm font-semibold text-gray-700 mb-2">{t('responses.selectAgent')}</label>
            <select
              value={targetAgentId || ''}
              onChange={(e) => setTargetAgentId(parseInt(e.target.value))}
              className="w-full px-3 py-2.5 border border-gray-200 rounded-input text-sm bg-white focus:ring-2 focus:ring-primary-500"
            >
              {agents.map((a) => (
                <option key={a.id} value={a.id}>{a.name}</option>
              ))}
            </select>
          </div>
        </div>
        <div className="px-6 py-4 border-t border-gray-100 flex justify-end gap-3">
          <button onClick={onClose} className="px-4 py-2 text-sm text-gray-600 hover:text-gray-800">Annuler</button>
          <button
            onClick={handleExport}
            disabled={exporting || !targetAgentId}
            className="flex items-center gap-2 px-4 py-2 bg-primary-600 text-white rounded-button text-sm font-medium hover:bg-primary-700 disabled:opacity-50"
          >
            {exporting ? <Loader2 className="w-4 h-4 animate-spin" /> : <Upload className="w-4 h-4" />}
            {t('responses.exportButton')}
          </button>
        </div>
      </div>
    </div>
  );
}
