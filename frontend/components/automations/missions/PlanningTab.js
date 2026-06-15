import { useState, useEffect, useCallback, useRef } from 'react';
import { useTranslation } from 'next-i18next';
import toast from 'react-hot-toast';
import { Upload, Plus, Trash2 } from 'lucide-react';
import api from '../../../lib/api';

export default function PlanningTab({ missionId }) {
  const { t } = useTranslation('automations');
  const [events, setEvents] = useState([]);
  const [review, setReview] = useState(null); // {events: [...], skipped} during validation
  const [parsing, setParsing] = useState(false);
  const [replaceUpload, setReplaceUpload] = useState(false);
  const fileRef = useRef(null);

  const load = useCallback(async () => {
    try {
      const res = await api.get(`/api/automations/missions/${missionId}/events`);
      setEvents(res.data.events || []);
    } catch {
      toast.error(t('errors.loadFailed'));
    }
  }, [missionId, t]);

  useEffect(() => {
    load();
  }, [load]);

  const handleFile = async (e) => {
    const file = e.target.files?.[0];
    if (!file) return;
    setParsing(true);
    const form = new FormData();
    form.append('file', file);
    try {
      const res = await api.post(`/api/automations/missions/${missionId}/planning/parse`, form, {
        headers: { 'Content-Type': 'multipart/form-data' },
      });
      setReview({ events: res.data.events, skipped: res.data.skipped });
      setReplaceUpload(events.length > 0);
    } catch (err) {
      toast.error(err.response?.data?.detail || t('missions.planning.parseFailed'));
    } finally {
      setParsing(false);
      if (fileRef.current) fileRef.current.value = '';
    }
  };

  const updateReviewRow = (i, field, value) => {
    setReview((r) => {
      const next = [...r.events];
      next[i] = { ...next[i], [field]: value };
      return { ...r, events: next };
    });
  };

  const removeReviewRow = (i) =>
    setReview((r) => ({ ...r, events: r.events.filter((_, idx) => idx !== i) }));

  const confirmReview = async () => {
    try {
      await api.post(`/api/automations/missions/${missionId}/events/bulk`, {
        events: review.events,
        replace_upload: replaceUpload,
      });
      toast.success(t('missions.planning.saved'));
      setReview(null);
      load();
    } catch {
      toast.error(t('errors.saveFailed'));
    }
  };

  const addManual = async () => {
    const today = new Date().toISOString().slice(0, 10);
    try {
      await api.post(`/api/automations/missions/${missionId}/events`, {
        date: today,
        title: t('missions.planning.titleLabel'),
      });
      load();
    } catch {
      toast.error(t('errors.saveFailed'));
    }
  };

  const deleteEvent = async (id) => {
    if (!window.confirm(t('missions.planning.deleteConfirm'))) return;
    try {
      await api.delete(`/api/automations/missions/${missionId}/events/${id}`);
      load();
    } catch {
      toast.error(t('errors.saveFailed'));
    }
  };

  if (review) {
    return (
      <div>
        <p className="text-sm font-medium text-gray-800 mb-1">{t('missions.planning.reviewTitle')}</p>
        <p className="text-xs text-gray-400 mb-4">
          {t('missions.planning.reviewHint', { skipped: review.skipped })}
        </p>
        <div className="space-y-2 mb-4">
          {review.events.map((ev, i) => (
            <div key={i} className="flex gap-2 items-center">
              <input
                type="date"
                value={ev.date}
                onChange={(e) => updateReviewRow(i, 'date', e.target.value)}
                className="px-2 py-1.5 border border-gray-300 rounded-button text-sm"
              />
              <input
                value={ev.title}
                onChange={(e) => updateReviewRow(i, 'title', e.target.value)}
                className="flex-1 px-2 py-1.5 border border-gray-300 rounded-button text-sm"
              />
              <button
                onClick={() => removeReviewRow(i)}
                className="p-1.5 text-gray-300 hover:text-red-500"
              >
                <Trash2 className="w-4 h-4" />
              </button>
            </div>
          ))}
        </div>
        <label className="flex items-center gap-2 text-sm text-gray-600 mb-4">
          <input
            type="checkbox"
            checked={replaceUpload}
            onChange={(e) => setReplaceUpload(e.target.checked)}
          />
          {t('missions.planning.replaceUpload')}
        </label>
        <div className="flex gap-2">
          <button
            onClick={confirmReview}
            className="px-4 py-2 bg-primary-600 text-white text-sm font-semibold rounded-button hover:bg-primary-700"
          >
            {t('missions.planning.confirm')}
          </button>
          <button
            onClick={() => setReview(null)}
            className="px-4 py-2 text-sm text-gray-500 hover:text-gray-800"
          >
            {t('missions.planning.cancel')}
          </button>
        </div>
      </div>
    );
  }

  const today = new Date().toISOString().slice(0, 10);
  const upcoming = events.filter((e) => e.date >= today);
  const past = events.filter((e) => e.date < today);

  return (
    <div>
      <div className="flex items-center gap-2 mb-4">
        <button
          onClick={() => fileRef.current?.click()}
          disabled={parsing}
          className="flex items-center gap-2 px-4 py-2 bg-primary-600 text-white text-sm font-semibold rounded-button hover:bg-primary-700 disabled:opacity-50"
        >
          <Upload className="w-4 h-4" />
          {parsing ? t('missions.planning.parsing') : t('missions.planning.upload')}
        </button>
        <button
          onClick={addManual}
          className="flex items-center gap-2 px-4 py-2 border border-gray-300 text-gray-700 text-sm font-medium rounded-button hover:border-primary-300"
        >
          <Plus className="w-4 h-4" />
          {t('missions.planning.addManual')}
        </button>
        <input
          ref={fileRef}
          type="file"
          className="hidden"
          accept=".pdf,.txt,.csv,.docx,.xlsx,.pptx,.json"
          onChange={handleFile}
        />
      </div>
      <p className="text-xs text-gray-400 mb-6">{t('missions.planning.uploadHint')}</p>

      {events.length === 0 ? (
        <p className="text-sm text-gray-400 py-8 text-center">{t('missions.planning.empty')}</p>
      ) : (
        <EventGroups
          upcoming={upcoming}
          past={past}
          onDelete={deleteEvent}
          labels={{
            upcoming: t('missions.planning.upcoming'),
            past: t('missions.planning.past'),
          }}
        />
      )}
    </div>
  );
}

function EventGroups({ upcoming, past, onDelete, labels }) {
  return (
    <div className="space-y-6">
      {[
        { title: labels.upcoming, list: upcoming },
        { title: labels.past, list: past },
      ].map(
        (group) =>
          group.list.length > 0 && (
            <div key={group.title}>
              <p className="text-xs font-semibold text-gray-400 uppercase mb-2">{group.title}</p>
              <div className="space-y-1.5">
                {group.list.map((e) => (
                  <div
                    key={e.id}
                    className="flex items-center gap-3 px-3 py-2 bg-white border border-gray-200 rounded-card"
                  >
                    <span className="text-xs font-mono text-gray-500 shrink-0">{e.date}</span>
                    <span className="flex-1 text-sm text-gray-800 truncate">{e.title}</span>
                    <button
                      onClick={() => onDelete(e.id)}
                      className="p-1 text-gray-300 hover:text-red-500"
                    >
                      <Trash2 className="w-4 h-4" />
                    </button>
                  </div>
                ))}
              </div>
            </div>
          )
      )}
    </div>
  );
}
