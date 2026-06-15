import { useState, useEffect, useCallback } from 'react';
import { useTranslation } from 'next-i18next';
import toast from 'react-hot-toast';
import { Sparkles } from 'lucide-react';
import api from '../../../lib/api';
import MarkdownRenderer from '../../MarkdownRenderer';

export default function RecapsTab({ missionId, hasCompanion }) {
  const { t } = useTranslation('automations');
  const [recaps, setRecaps] = useState([]);
  const [generating, setGenerating] = useState(false);

  const load = useCallback(async () => {
    try {
      const res = await api.get(`/api/automations/missions/${missionId}/recaps`);
      setRecaps(res.data.recaps || []);
    } catch {
      toast.error(t('errors.loadFailed'));
    }
  }, [missionId, t]);

  useEffect(() => {
    load();
  }, [load]);

  const generate = async () => {
    setGenerating(true);
    try {
      await api.post(`/api/automations/missions/${missionId}/recaps/generate`);
      toast.success(t('missions.recaps.generated'));
      load();
    } catch (err) {
      toast.error(err.response?.data?.detail || t('missions.recaps.error'));
    } finally {
      setGenerating(false);
    }
  };

  return (
    <div>
      <button
        onClick={generate}
        disabled={generating || !hasCompanion}
        className="flex items-center gap-2 px-4 py-2 bg-primary-600 text-white text-sm font-semibold rounded-button hover:bg-primary-700 disabled:opacity-50 mb-4"
      >
        <Sparkles className="w-4 h-4" />
        {generating ? t('missions.recaps.generating') : t('missions.recaps.generate')}
      </button>
      {!hasCompanion && (
        <p className="text-xs text-amber-600 mb-4">{t('missions.recaps.noCompanion')}</p>
      )}

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
                  {r.status === 'no_data'
                    ? t('missions.recaps.noData')
                    : t('missions.recaps.error')}
                </p>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
