import { useState, useEffect, useCallback, useRef } from 'react';
import { useTranslation } from 'next-i18next';
import toast from 'react-hot-toast';
import { Plus, Trash2, Upload, FileText, Sparkles } from 'lucide-react';
import api from '../../../lib/api';

function todayIso() {
  return new Date().toISOString().slice(0, 10);
}

export default function RecapSchedules({ missionId, hasCompanion, onGenerated }) {
  const { t } = useTranslation('automations');
  const [schedules, setSchedules] = useState([]);

  const load = useCallback(async () => {
    try {
      const res = await api.get(`/api/automations/missions/${missionId}/recap-schedules`);
      setSchedules(res.data.schedules || []);
    } catch {
      toast.error(t('errors.loadFailed'));
    }
  }, [missionId, t]);

  useEffect(() => {
    load();
  }, [load]);

  const add = async () => {
    try {
      await api.post(`/api/automations/missions/${missionId}/recap-schedules`, {
        kind: 'recurring',
        weekday: 0,
        hour: 8,
        enabled: true,
      });
      load();
    } catch {
      toast.error(t('errors.saveFailed'));
    }
  };

  const save = async (id, payload) => {
    try {
      await api.put(`/api/automations/missions/${missionId}/recap-schedules/${id}`, payload);
      toast.success(t('missions.settings.recapSchedules.saved'));
      load();
    } catch {
      toast.error(t('errors.saveFailed'));
    }
  };

  const remove = async (id) => {
    try {
      await api.delete(`/api/automations/missions/${missionId}/recap-schedules/${id}`);
      toast.success(t('missions.settings.recapSchedules.deleted'));
      load();
    } catch {
      toast.error(t('errors.saveFailed'));
    }
  };

  const weekdays = t('missions.settings.weekdays', { returnObjects: true });

  return (
    <div>
      <div className="flex items-center justify-between mb-3">
        <p className="text-sm font-medium text-gray-800">
          {t('missions.settings.recapSchedules.title')}
        </p>
        <button
          onClick={add}
          className="flex items-center gap-1.5 px-3 py-1.5 border border-gray-300 text-gray-700 text-sm font-medium rounded-button hover:border-primary-300"
        >
          <Plus className="w-4 h-4" />
          {t('missions.settings.recapSchedules.add')}
        </button>
      </div>

      {schedules.length === 0 ? (
        <p className="text-sm text-gray-400 py-4">{t('missions.settings.recapSchedules.empty')}</p>
      ) : (
        <div className="space-y-3">
          {schedules.map((s) => (
            <ScheduleCard
              key={s.id}
              missionId={missionId}
              schedule={s}
              weekdays={weekdays}
              hasCompanion={hasCompanion}
              onSave={save}
              onDelete={remove}
              onGenerated={onGenerated}
              t={t}
            />
          ))}
        </div>
      )}
    </div>
  );
}

function ScheduleCard({ missionId, schedule, weekdays, hasCompanion, onSave, onDelete, onGenerated, t }) {
  const [kind, setKind] = useState(schedule.kind);
  const [weekday, setWeekday] = useState(schedule.weekday ?? 0);
  const [runDate, setRunDate] = useState(schedule.run_date ?? todayIso());
  const [hour, setHour] = useState(schedule.hour);
  const [enabled, setEnabled] = useState(schedule.enabled);
  const [recapPrompt, setRecapPrompt] = useState(schedule.recap_prompt ?? '');
  const [recipients, setRecipients] = useState((schedule.recipients ?? []).join(', '));

  useEffect(() => {
    setKind(schedule.kind);
    setWeekday(schedule.weekday ?? 0);
    setRunDate(schedule.run_date ?? todayIso());
    setHour(schedule.hour);
    setEnabled(schedule.enabled);
    setRecapPrompt(schedule.recap_prompt ?? '');
    setRecipients((schedule.recipients ?? []).join(', '));
  }, [schedule]);

  const commit = (overrides = {}) => {
    const next = {
      kind,
      weekday,
      run_date: runDate,
      hour,
      enabled,
      recap_prompt: recapPrompt,
      recipients,
      ...overrides,
    };
    onSave(schedule.id, {
      kind: next.kind,
      weekday: next.kind === 'recurring' ? parseInt(next.weekday, 10) : null,
      run_date: next.kind === 'once' ? next.run_date : null,
      hour: parseInt(next.hour, 10),
      enabled: next.enabled,
      recap_prompt: next.recap_prompt,
      recipients: next.recipients
        .split(',')
        .map((e) => e.trim())
        .filter(Boolean),
    });
  };

  // --- documents for this scheduled recap (sync upload) ---
  const [docs, setDocs] = useState([]);
  const [uploading, setUploading] = useState(false);
  const fileRef = useRef(null);

  const loadDocs = useCallback(async () => {
    try {
      const res = await api.get(
        `/api/automations/missions/${missionId}/recap-schedules/${schedule.id}/documents`
      );
      setDocs(res.data.documents || []);
    } catch {
      toast.error(t('errors.loadFailed'));
    }
  }, [missionId, schedule.id, t]);

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
      await api.post(
        `/api/automations/missions/${missionId}/recap-schedules/${schedule.id}/documents`,
        fd,
        { headers: { 'Content-Type': 'multipart/form-data' } }
      );
      toast.success(t('missions.settings.recapSchedules.docsUploaded'));
      loadDocs();
    } catch {
      toast.error(t('errors.saveFailed'));
    } finally {
      setUploading(false);
      if (fileRef.current) fileRef.current.value = '';
    }
  };

  const deleteDoc = async (id) => {
    if (!window.confirm(t('missions.settings.recapSchedules.docsDeleteConfirm'))) return;
    try {
      await api.delete(
        `/api/automations/missions/${missionId}/recap-schedules/${schedule.id}/documents/${id}`
      );
      loadDocs();
    } catch {
      toast.error(t('errors.saveFailed'));
    }
  };

  // --- manual generation for this recap ---
  const [generating, setGenerating] = useState(false);
  const generate = async () => {
    setGenerating(true);
    try {
      await api.post(
        `/api/automations/missions/${missionId}/recap-schedules/${schedule.id}/generate`
      );
      toast.success(t('missions.settings.recapSchedules.generated'));
      onGenerated?.();
    } catch (err) {
      toast.error(err.response?.data?.detail || t('missions.recaps.error'));
    } finally {
      setGenerating(false);
    }
  };

  return (
    <div className="px-3 py-3 bg-white border border-gray-200 rounded-card space-y-3">
      {/* timing row */}
      <div className="flex flex-wrap items-center gap-2">
        <input
          type="checkbox"
          checked={enabled}
          onChange={(e) => {
            setEnabled(e.target.checked);
            commit({ enabled: e.target.checked });
          }}
          title={t('missions.settings.recapSchedules.enabled')}
        />

        <select
          value={kind}
          onChange={(e) => {
            const newKind = e.target.value;
            setKind(newKind);
            // Persist immediately only when switching to recurring: its default
            // weekday is a valid choice. For one-shot we wait for the date input's
            // onBlur, so we never persist an unchosen run_date the scheduler could
            // fire today.
            if (newKind === 'recurring') {
              commit({ kind: newKind });
            }
          }}
          className="px-2 py-1.5 border border-gray-300 rounded-button text-sm bg-white"
        >
          <option value="recurring">{t('missions.settings.recapSchedules.recurring')}</option>
          <option value="once">{t('missions.settings.recapSchedules.once')}</option>
        </select>

        {kind === 'recurring' ? (
          <select
            value={weekday}
            onChange={(e) => setWeekday(e.target.value)}
            onBlur={() => commit()}
            className="px-2 py-1.5 border border-gray-300 rounded-button text-sm bg-white"
          >
            {[0, 1, 2, 3, 4, 5, 6].map((d) => (
              <option key={d} value={d}>
                {weekdays[String(d)]}
              </option>
            ))}
          </select>
        ) : (
          <input
            type="date"
            value={runDate}
            onChange={(e) => setRunDate(e.target.value)}
            onBlur={() => commit()}
            className="px-2 py-1.5 border border-gray-300 rounded-button text-sm"
          />
        )}

        <select
          value={hour}
          onChange={(e) => setHour(e.target.value)}
          onBlur={() => commit()}
          className="px-2 py-1.5 border border-gray-300 rounded-button text-sm bg-white"
        >
          {Array.from({ length: 24 }, (_, h) => (
            <option key={h} value={h}>
              {String(h).padStart(2, '0')}:00
            </option>
          ))}
        </select>

        <button
          onClick={() => onDelete(schedule.id)}
          className="p-1.5 text-gray-300 hover:text-red-500 ml-auto"
        >
          <Trash2 className="w-4 h-4" />
        </button>
      </div>

      {/* this recap's prompt */}
      <div>
        <label className="block text-xs font-medium text-gray-600 mb-1">
          {t('missions.settings.recapSchedules.prompt')}
        </label>
        <textarea
          value={recapPrompt}
          onChange={(e) => setRecapPrompt(e.target.value)}
          onBlur={() => commit()}
          placeholder={t('missions.settings.recapSchedules.promptPlaceholder')}
          rows={3}
          className="w-full px-3 py-2 border border-gray-300 rounded-button text-sm"
        />
      </div>

      {/* this recap's recipients */}
      <div>
        <label className="block text-xs font-medium text-gray-600 mb-1">
          {t('missions.settings.recapSchedules.recipients')}
        </label>
        <input
          type="text"
          value={recipients}
          onChange={(e) => setRecipients(e.target.value)}
          onBlur={() => commit()}
          placeholder={t('missions.settings.recapSchedules.recipientsPlaceholder')}
          className="w-full px-3 py-2 border border-gray-300 rounded-button text-sm"
        />
        <p className="text-xs text-gray-400 mt-1">{t('missions.settings.recapSchedules.recipientsHint')}</p>
      </div>

      {/* this recap's documents */}
      <div>
        <div className="flex items-center justify-between mb-2">
          <p className="text-xs font-medium text-gray-600">
            {t('missions.settings.recapSchedules.docsTitle')}
          </p>
          <button
            onClick={() => fileRef.current?.click()}
            disabled={uploading}
            className="flex items-center gap-1.5 px-2.5 py-1 border border-gray-300 text-gray-700 text-xs font-medium rounded-button hover:border-primary-300 disabled:opacity-50"
          >
            <Upload className="w-3.5 h-3.5" />
            {uploading
              ? t('missions.settings.recapSchedules.docsUploading')
              : t('missions.settings.recapSchedules.docsUpload')}
          </button>
        </div>
        <input
          ref={fileRef}
          type="file"
          className="hidden"
          accept=".pdf,.txt,.csv,.docx,.xlsx,.pptx,.json"
          onChange={handleFile}
        />
        {docs.length === 0 ? (
          <p className="text-xs text-gray-400">{t('missions.settings.recapSchedules.docsEmpty')}</p>
        ) : (
          <div className="space-y-1.5">
            {docs.map((d) => (
              <div
                key={d.id}
                className="flex items-center gap-2 px-2.5 py-1.5 bg-gray-50 border border-gray-200 rounded-card"
              >
                <FileText className="w-3.5 h-3.5 text-gray-400 shrink-0" />
                <span className="flex-1 text-xs text-gray-700 truncate">{d.filename}</span>
                <button
                  onClick={() => deleteDoc(d.id)}
                  className="p-0.5 text-gray-300 hover:text-red-500"
                >
                  <Trash2 className="w-3.5 h-3.5" />
                </button>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* generate this recap now */}
      <div>
        <button
          onClick={generate}
          disabled={generating || !hasCompanion}
          className="flex items-center gap-2 px-3 py-1.5 bg-primary-600 text-white text-sm font-semibold rounded-button hover:bg-primary-700 disabled:opacity-50"
        >
          <Sparkles className="w-4 h-4" />
          {generating
            ? t('missions.settings.recapSchedules.generating')
            : t('missions.settings.recapSchedules.generate')}
        </button>
        {!hasCompanion && (
          <p className="text-xs text-amber-600 mt-1">
            {t('missions.settings.recapSchedules.noCompanion')}
          </p>
        )}
      </div>
    </div>
  );
}
