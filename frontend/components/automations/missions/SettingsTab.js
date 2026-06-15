import { useState, useEffect } from 'react';
import { useTranslation } from 'next-i18next';
import toast from 'react-hot-toast';
import api from '../../../lib/api';

export default function SettingsTab({ mission, onChanged, onDeleted }) {
  const { t } = useTranslation('automations');
  const [form, setForm] = useState({
    name: mission.name,
    objective: mission.objective,
    agent_id: mission.agent_id || '',
    status: mission.status,
    recap_enabled: mission.recap_enabled,
    recap_weekday: mission.recap_weekday,
    recap_hour: mission.recap_hour,
  });
  const [agents, setAgents] = useState([]);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    api
      .get('/agents')
      .then((res) => setAgents(res.data.agents || []))
      .catch(() => setAgents([]));
  }, []);

  const save = async (overrides = {}) => {
    setSaving(true);
    const merged = { ...form, ...overrides };
    const payload = {
      ...merged,
      agent_id: merged.agent_id ? parseInt(merged.agent_id, 10) : null,
      recap_weekday: parseInt(merged.recap_weekday, 10),
      recap_hour: parseInt(merged.recap_hour, 10),
    };
    try {
      await api.put(`/api/automations/missions/${mission.id}`, payload);
      toast.success(t('missions.settings.saved'));
      onChanged?.();
    } catch {
      toast.error(t('errors.saveFailed'));
    } finally {
      setSaving(false);
    }
  };

  const remove = async () => {
    if (!window.confirm(t('missions.list.deleteConfirm'))) return;
    try {
      await api.delete(`/api/automations/missions/${mission.id}`);
      toast.success(t('missions.list.deleted'));
      onDeleted?.();
    } catch {
      toast.error(t('errors.saveFailed'));
    }
  };

  const weekdays = t('missions.settings.weekdays', { returnObjects: true });

  return (
    <div className="max-w-xl space-y-4">
      <label className="flex items-center gap-2 text-sm text-gray-700">
        <input
          type="checkbox"
          checked={form.recap_enabled}
          onChange={(e) => setForm({ ...form, recap_enabled: e.target.checked })}
        />
        {t('missions.settings.recapEnabled')}
      </label>

      <div className="flex gap-4">
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">
            {t('missions.settings.weekday')}
          </label>
          <select
            value={form.recap_weekday}
            onChange={(e) => setForm({ ...form, recap_weekday: e.target.value })}
            className="px-3 py-2 border border-gray-300 rounded-button text-sm bg-white"
          >
            {[0, 1, 2, 3, 4, 5, 6].map((d) => (
              <option key={d} value={d}>
                {weekdays[String(d)]}
              </option>
            ))}
          </select>
        </div>
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">
            {t('missions.settings.hour')}
          </label>
          <select
            value={form.recap_hour}
            onChange={(e) => setForm({ ...form, recap_hour: e.target.value })}
            className="px-3 py-2 border border-gray-300 rounded-button text-sm bg-white"
          >
            {Array.from({ length: 24 }, (_, h) => (
              <option key={h} value={h}>
                {String(h).padStart(2, '0')}:00
              </option>
            ))}
          </select>
        </div>
      </div>

      <div>
        <label className="block text-sm font-medium text-gray-700 mb-1">
          {t('missions.settings.companion')}
        </label>
        <select
          value={form.agent_id}
          onChange={(e) => setForm({ ...form, agent_id: e.target.value })}
          className="w-full px-3 py-2 border border-gray-300 rounded-button text-sm bg-white"
        >
          <option value="">{t('missions.editor.selectCompanion')}</option>
          {agents.map((a) => (
            <option key={a.id} value={a.id}>
              {a.name}
            </option>
          ))}
        </select>
      </div>

      <div className="flex gap-2 pt-2">
        <button
          onClick={() => save()}
          disabled={saving}
          className="px-4 py-2 bg-primary-600 text-white text-sm font-semibold rounded-button hover:bg-primary-700 disabled:opacity-50"
        >
          {t('missions.settings.save')}
        </button>
        <button
          onClick={() => save({ status: form.status === 'active' ? 'archived' : 'active' })}
          className="px-4 py-2 border border-gray-300 text-gray-700 text-sm font-medium rounded-button hover:border-primary-300"
        >
          {form.status === 'active'
            ? t('missions.settings.archive')
            : t('missions.settings.unarchive')}
        </button>
        <button
          onClick={remove}
          className="px-4 py-2 text-sm text-red-500 hover:text-red-700 ml-auto"
        >
          {t('missions.settings.delete')}
        </button>
      </div>
    </div>
  );
}
