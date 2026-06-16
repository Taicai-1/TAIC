import { useState, useEffect, useCallback } from 'react';
import { useTranslation } from 'next-i18next';
import toast from 'react-hot-toast';
import { Plus, Trash2 } from 'lucide-react';
import api from '../../../lib/api';

function todayIso() {
  return new Date().toISOString().slice(0, 10);
}

export default function RecapSchedules({ missionId }) {
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
        <div className="space-y-2">
          {schedules.map((s) => (
            <ScheduleRow
              key={s.id}
              schedule={s}
              weekdays={weekdays}
              onSave={save}
              onDelete={remove}
              t={t}
            />
          ))}
        </div>
      )}
    </div>
  );
}

function ScheduleRow({ schedule, weekdays, onSave, onDelete, t }) {
  const [kind, setKind] = useState(schedule.kind);
  const [weekday, setWeekday] = useState(schedule.weekday ?? 0);
  const [runDate, setRunDate] = useState(schedule.run_date ?? todayIso());
  const [hour, setHour] = useState(schedule.hour);
  const [enabled, setEnabled] = useState(schedule.enabled);

  useEffect(() => {
    setKind(schedule.kind);
    setWeekday(schedule.weekday ?? 0);
    setRunDate(schedule.run_date ?? todayIso());
    setHour(schedule.hour);
    setEnabled(schedule.enabled);
  }, [schedule]);

  const commit = (overrides = {}) => {
    const next = { kind, weekday, run_date: runDate, hour, enabled, ...overrides };
    onSave(schedule.id, {
      kind: next.kind,
      weekday: next.kind === 'recurring' ? parseInt(next.weekday, 10) : null,
      run_date: next.kind === 'once' ? next.run_date : null,
      hour: parseInt(next.hour, 10),
      enabled: next.enabled,
    });
  };

  return (
    <div className="flex flex-wrap items-center gap-2 px-3 py-2 bg-white border border-gray-200 rounded-card">
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
          setKind(e.target.value);
          commit({ kind: e.target.value });
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
  );
}
