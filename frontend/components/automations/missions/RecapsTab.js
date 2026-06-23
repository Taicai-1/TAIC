import { useState, useEffect, useCallback, useRef } from 'react';
import { useTranslation } from 'next-i18next';
import toast from 'react-hot-toast';
import { Sparkles, Upload, FileText, Trash2 } from 'lucide-react';
import api from '../../../lib/api';
import MarkdownRenderer from '../../MarkdownRenderer';
import RecapSchedules from './RecapSchedules';

export default function RecapsTab({ mission, onChanged, onDeleted }) {
  const { t } = useTranslation('automations');
  const missionId = mission.id;
  const hasCompanion = !!mission.agent_id;

  // --- mission form (shared by prompt save + companion/archive/delete) ---
  const [form, setForm] = useState({
    name: mission.name,
    objective: mission.objective,
    agent_id: mission.agent_id || '',
    status: mission.status,
    recap_prompt: mission.recap_prompt || '',
  });
  const [agents, setAgents] = useState([]);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    setForm({
      name: mission.name,
      objective: mission.objective,
      agent_id: mission.agent_id || '',
      status: mission.status,
      recap_prompt: mission.recap_prompt || '',
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

  // --- recap documents (sync upload: endpoint returns immediately) ---
  const [docs, setDocs] = useState([]);
  const [uploading, setUploading] = useState(false);
  const fileRef = useRef(null);

  const loadDocs = useCallback(async () => {
    try {
      const res = await api.get(`/api/automations/missions/${missionId}/recap-documents`);
      setDocs(res.data.documents || []);
    } catch {
      toast.error(t('errors.loadFailed'));
    }
  }, [missionId, t]);

  useEffect(() => {
    loadDocs();
  }, [loadDocs]);

  const handleFile = async (e) => {
    const file = e.target.files?.[0];
    if (!file) return;
    setUploading(true);
    const fd = new FormData();
    fd.append('file', file);
    try {
      await api.post(`/api/automations/missions/${missionId}/recap-documents`, fd, {
        headers: { 'Content-Type': 'multipart/form-data' },
      });
      toast.success(t('missions.recaps.docsUploaded'));
      loadDocs();
    } catch {
      toast.error(t('errors.saveFailed'));
    } finally {
      setUploading(false);
      if (fileRef.current) fileRef.current.value = '';
    }
  };

  const deleteDoc = async (id) => {
    if (!window.confirm(t('missions.recaps.docsDeleteConfirm'))) return;
    try {
      await api.delete(`/api/automations/missions/${missionId}/recap-documents/${id}`);
      loadDocs();
    } catch {
      toast.error(t('errors.saveFailed'));
    }
  };

  // --- generated recaps ---
  const [recaps, setRecaps] = useState([]);
  const [generating, setGenerating] = useState(false);

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

  const generate = async () => {
    setGenerating(true);
    try {
      await api.post(`/api/automations/missions/${missionId}/recaps/generate`);
      toast.success(t('missions.recaps.generated'));
      loadRecaps();
    } catch (err) {
      toast.error(err.response?.data?.detail || t('missions.recaps.error'));
    } finally {
      setGenerating(false);
    }
  };

  return (
    <div className="max-w-2xl space-y-8">
      {/* 1. Recap prompt */}
      <section>
        <h3 className="text-sm font-semibold text-gray-800 mb-2">{t('missions.recaps.promptTitle')}</h3>
        <textarea
          value={form.recap_prompt}
          onChange={(e) => setForm({ ...form, recap_prompt: e.target.value })}
          placeholder={t('missions.recaps.promptPlaceholder')}
          rows={5}
          className="w-full px-3 py-2 border border-gray-300 rounded-button text-sm"
        />
        <button
          onClick={() => save()}
          disabled={saving}
          className="mt-2 px-4 py-2 bg-primary-600 text-white text-sm font-semibold rounded-button hover:bg-primary-700 disabled:opacity-50"
        >
          {t('missions.recaps.promptSave')}
        </button>
      </section>

      {/* 2. Recap documents */}
      <section>
        <h3 className="text-sm font-semibold text-gray-800 mb-1">{t('missions.recaps.docsTitle')}</h3>
        <p className="text-xs text-gray-500 mb-3">{t('missions.recaps.docsHint')}</p>
        <button
          onClick={() => fileRef.current?.click()}
          disabled={uploading}
          className="flex items-center gap-2 px-4 py-2 bg-primary-600 text-white text-sm font-semibold rounded-button hover:bg-primary-700 disabled:opacity-50 mb-3"
        >
          <Upload className="w-4 h-4" />
          {uploading ? t('missions.recaps.docsUploading') : t('missions.recaps.docsUpload')}
        </button>
        <input
          ref={fileRef}
          type="file"
          className="hidden"
          accept=".pdf,.txt,.csv,.docx,.xlsx,.pptx,.json"
          onChange={handleFile}
        />
        {docs.length === 0 ? (
          <p className="text-sm text-gray-400 py-4 text-center">{t('missions.recaps.docsEmpty')}</p>
        ) : (
          <div className="space-y-1.5">
            {docs.map((d) => (
              <div key={d.id} className="flex items-center gap-3 px-3 py-2 bg-white border border-gray-200 rounded-card">
                <FileText className="w-4 h-4 text-gray-400 shrink-0" />
                <span className="flex-1 text-sm text-gray-800 truncate">{d.filename}</span>
                <button onClick={() => deleteDoc(d.id)} className="p-1 text-gray-300 hover:text-red-500">
                  <Trash2 className="w-4 h-4" />
                </button>
              </div>
            ))}
          </div>
        )}
      </section>

      {/* 3. Schedules */}
      <section>
        <RecapSchedules missionId={missionId} />
      </section>

      {/* 4. Generated recaps */}
      <section>
        <button
          onClick={generate}
          disabled={generating || !hasCompanion}
          className="flex items-center gap-2 px-4 py-2 bg-primary-600 text-white text-sm font-semibold rounded-button hover:bg-primary-700 disabled:opacity-50 mb-4"
        >
          <Sparkles className="w-4 h-4" />
          {generating ? t('missions.recaps.generating') : t('missions.recaps.generate')}
        </button>
        {!hasCompanion && <p className="text-xs text-amber-600 mb-4">{t('missions.recaps.noCompanion')}</p>}
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

      {/* 5. Mission lifecycle */}
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
