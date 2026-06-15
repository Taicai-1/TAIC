import { useState, useEffect } from 'react';
import { useTranslation } from 'next-i18next';
import toast from 'react-hot-toast';
import api from '../../../lib/api';

export default function MissionEditor({ onSaved, onCancel }) {
  const { t } = useTranslation('automations');
  const [name, setName] = useState('');
  const [objective, setObjective] = useState('');
  const [agentId, setAgentId] = useState('');
  const [agents, setAgents] = useState([]);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    api
      .get('/agents')
      .then((res) => setAgents(res.data.agents || []))
      .catch(() => setAgents([]));
  }, []);

  const handleSave = async () => {
    if (!name.trim()) {
      toast.error(t('missions.editor.nameRequired'));
      return;
    }
    if (!objective.trim()) {
      toast.error(t('missions.editor.objectiveRequired'));
      return;
    }
    setSaving(true);
    try {
      const res = await api.post('/api/automations/missions', {
        name: name.trim(),
        objective: objective.trim(),
        agent_id: agentId ? parseInt(agentId, 10) : null,
      });
      toast.success(t('missions.editor.saved'));
      onSaved?.(res.data.mission);
    } catch {
      toast.error(t('errors.saveFailed'));
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="max-w-2xl">
      <h2 className="text-xl font-bold text-gray-900 mb-6">{t('missions.editor.createTitle')}</h2>

      <label className="block text-sm font-medium text-gray-700 mb-1">
        {t('missions.editor.nameLabel')}
      </label>
      <input
        value={name}
        onChange={(e) => setName(e.target.value)}
        placeholder={t('missions.editor.namePlaceholder')}
        className="w-full mb-4 px-3 py-2 border border-gray-300 rounded-button text-sm focus:border-primary-500 focus:outline-none"
      />

      <label className="block text-sm font-medium text-gray-700 mb-1">
        {t('missions.editor.objectiveLabel')}
      </label>
      <textarea
        value={objective}
        onChange={(e) => setObjective(e.target.value)}
        placeholder={t('missions.editor.objectivePlaceholder')}
        rows={4}
        className="w-full mb-4 px-3 py-2 border border-gray-300 rounded-button text-sm focus:border-primary-500 focus:outline-none"
      />

      <label className="block text-sm font-medium text-gray-700 mb-1">
        {t('missions.editor.companionLabel')}
      </label>
      <select
        value={agentId}
        onChange={(e) => setAgentId(e.target.value)}
        className="w-full mb-6 px-3 py-2 border border-gray-300 rounded-button text-sm bg-white focus:border-primary-500 focus:outline-none"
      >
        <option value="">{t('missions.editor.selectCompanion')}</option>
        {agents.map((a) => (
          <option key={a.id} value={a.id}>
            {a.name}
          </option>
        ))}
      </select>

      <div className="flex gap-2">
        <button
          onClick={handleSave}
          disabled={saving}
          className="px-4 py-2 bg-primary-600 text-white text-sm font-semibold rounded-button hover:bg-primary-700 disabled:opacity-50 transition-colors"
        >
          {t('missions.editor.save')}
        </button>
        <button
          onClick={onCancel}
          className="px-4 py-2 text-sm text-gray-500 hover:text-gray-800 transition-colors"
        >
          {t('missions.planning.cancel')}
        </button>
      </div>
    </div>
  );
}
