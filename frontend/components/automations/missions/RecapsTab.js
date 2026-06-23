import { useState, useEffect, useCallback } from 'react';
import { useTranslation } from 'next-i18next';
import toast from 'react-hot-toast';
import api from '../../../lib/api';
import MarkdownRenderer from '../../MarkdownRenderer';
import RecapSchedules from './RecapSchedules';

export default function RecapsTab({ mission, onChanged, onDeleted }) {
  const { t } = useTranslation('automations');
  const missionId = mission.id;
  const hasCompanion = !!mission.agent_id;

  // --- mission form (companion / archive / delete) ---
  const [form, setForm] = useState({
    name: mission.name,
    objective: mission.objective,
    agent_id: mission.agent_id || '',
    status: mission.status,
  });
  const [agents, setAgents] = useState([]);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    setForm({
      name: mission.name,
      objective: mission.objective,
      agent_id: mission.agent_id || '',
      status: mission.status,
    });
  }, [mission]);

  useEffect(() => {
    api.get('/agents').then((res) => setAgents(res.data.agents || [])).catch(() => setAgents([]));
  }, []);

  const save = async (overrides = {}) => {
    setSaving(true);
    const merged = { ...form, ...overrides };
    const payload = {
      ...merged,
      agent_id: merged.agent_id ? parseInt(merged.agent_id, 10) : null,
    };
    try {
      await api.put(`/api/automations/missions/${missionId}`, payload);
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
      await api.delete(`/api/automations/missions/${missionId}`);
      toast.success(t('missions.list.deleted'));
      onDeleted?.();
    } catch {
      toast.error(t('errors.saveFailed'));
    }
  };

  // --- generated recaps ---
  const [recaps, setRecaps] = useState([]);

  const loadRecaps = useCallback(async () => {
    try {
      const res = await api.get(`/api/automations/missions/${missionId}/recaps`);
      setRecaps(res.data.recaps || []);
    } catch {
      toast.error(t('errors.loadFailed'));
    }
  }, [missionId, t]);

  useEffect(() => {
    loadRecaps();
  }, [loadRecaps]);

  return (
    <div className="max-w-2xl space-y-8">
      {/* Scheduled recaps — each with its own prompt, documents and "generate now" */}
      <section>
        <RecapSchedules missionId={missionId} hasCompanion={hasCompanion} onGenerated={loadRecaps} />
      </section>

      {/* Generated recaps */}
      <section>
        <h3 className="text-sm font-semibold text-gray-800 mb-3">{t('missions.recaps.title')}</h3>
        {recaps.length === 0 ? (
          <p className="text-sm text-gray-400 py-8 text-center">{t('missions.recaps.empty')}</p>
        ) : (
          <div className="space-y-4">
            {recaps.map((r) => (
              <div key={r.id} className="border border-gray-200 rounded-card p-4 bg-white">
                <p className="text-xs text-gray-400 mb-2">
                  {t('missions.recaps.period', { start: r.period_start, end: r.period_end })}
                  {r.trigger === 'manual' && ' · manuel'}
                </p>
                {r.status === 'success' ? (
                  <MarkdownRenderer>{r.content}</MarkdownRenderer>
                ) : (
                  <p className="text-sm text-gray-500">
                    {r.status === 'no_data' ? t('missions.recaps.noData') : t('missions.recaps.error')}
                  </p>
                )}
              </div>
            ))}
          </div>
        )}
      </section>

      {/* Mission lifecycle */}
      <section className="border-t border-gray-200 pt-6">
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">{t('missions.settings.companion')}</label>
          <select
            value={form.agent_id}
            onChange={(e) => setForm({ ...form, agent_id: e.target.value })}
            className="w-full max-w-xs px-3 py-2 border border-gray-300 rounded-button text-sm bg-white"
          >
            <option value="">{t('missions.editor.selectCompanion')}</option>
            {agents.map((a) => (
              <option key={a.id} value={a.id}>{a.name}</option>
            ))}
          </select>
        </div>
        <div className="flex gap-2 pt-4">
          <button onClick={() => save()} disabled={saving} className="px-4 py-2 bg-primary-600 text-white text-sm font-semibold rounded-button hover:bg-primary-700 disabled:opacity-50">
            {t('missions.settings.save')}
          </button>
          <button onClick={() => save({ status: form.status === 'active' ? 'archived' : 'active' })} className="px-4 py-2 border border-gray-300 text-gray-700 text-sm font-medium rounded-button hover:border-primary-300">
            {form.status === 'active' ? t('missions.settings.archive') : t('missions.settings.unarchive')}
          </button>
          <button onClick={remove} className="px-4 py-2 text-sm text-red-500 hover:text-red-700 ml-auto">
            {t('missions.settings.delete')}
          </button>
        </div>
      </section>
    </div>
  );
}
