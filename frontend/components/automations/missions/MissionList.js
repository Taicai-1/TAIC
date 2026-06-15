import { useTranslation } from 'next-i18next';
import { Plus, Trash2, Target } from 'lucide-react';

export default function MissionList({ missions, onOpen, onCreate, onDelete }) {
  const { t } = useTranslation('automations');

  return (
    <div>
      <div className="flex items-center justify-between mb-4">
        <span className="text-sm text-gray-500">
          {missions.length > 0 && t('missions.list.count', { count: missions.length })}
        </span>
        <button
          onClick={onCreate}
          className="flex items-center gap-2 px-4 py-2 bg-primary-600 text-white text-sm font-semibold rounded-button hover:bg-primary-700 transition-colors"
        >
          <Plus className="w-4 h-4" />
          {t('missions.list.create')}
        </button>
      </div>

      {missions.length === 0 ? (
        <div className="text-center py-16 border border-dashed border-gray-200 rounded-card">
          <Target className="w-10 h-10 text-gray-300 mx-auto mb-3" />
          <p className="text-sm font-medium text-gray-600">{t('missions.list.empty')}</p>
          <p className="text-xs text-gray-400 mt-1">{t('missions.list.emptyHint')}</p>
        </div>
      ) : (
        <div className="grid gap-3">
          {missions.map((m) => (
            <div
              key={m.id}
              onClick={() => onOpen(m.id)}
              className="flex items-center gap-4 px-5 py-4 bg-white border border-gray-200 rounded-card shadow-subtle hover:border-primary-300 cursor-pointer transition-colors"
            >
              <div className="w-10 h-10 rounded-sm bg-primary-50 flex items-center justify-center shrink-0">
                <Target className="w-5 h-5 text-primary-600" />
              </div>
              <div className="flex-1 min-w-0">
                <p className="text-sm font-semibold text-gray-900 truncate">{m.name}</p>
                <p className="text-xs text-gray-400 truncate">{m.objective}</p>
              </div>
              <div className="text-xs text-gray-500 text-right shrink-0">
                <p>
                  {m.last_recap_at
                    ? t('missions.list.lastRecap', {
                        date: new Date(m.last_recap_at).toLocaleDateString(),
                      })
                    : t('missions.list.neverRecap')}
                </p>
              </div>
              <button
                onClick={(e) => {
                  e.stopPropagation();
                  onDelete(m.id);
                }}
                className="p-1.5 text-gray-300 hover:text-red-500 transition-colors"
              >
                <Trash2 className="w-4 h-4" />
              </button>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
