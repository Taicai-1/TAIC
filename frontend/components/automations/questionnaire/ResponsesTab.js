import { useState, useEffect, useCallback } from 'react';
import { useTranslation } from 'next-i18next';
import toast from 'react-hot-toast';
import { ChevronDown, ChevronUp, Trash2, Upload } from 'lucide-react';
import api from '../../../lib/api';
import ExportModal from './ExportModal';
import { STATUS_BADGE_CLASSES } from './constants';

const PAGE_SIZE = 50;

export default function ResponsesTab({ questionnaireId }) {
  const { t } = useTranslation('automations');
  const [responses, setResponses] = useState([]);
  const [filteredTotal, setFilteredTotal] = useState(0);
  const [statusFilter, setStatusFilter] = useState(null);
  const [details, setDetails] = useState({});
  const [expanded, setExpanded] = useState(null);
  const [selected, setSelected] = useState([]);
  const [showExport, setShowExport] = useState(false);

  const load = useCallback(
    async (offset = 0, append = false) => {
      try {
        const params = new URLSearchParams({ limit: String(PAGE_SIZE), offset: String(offset) });
        if (statusFilter) params.set('status', statusFilter);
        const res = await api.get(
          `/api/automations/questionnaires/${questionnaireId}/responses?${params}`
        );
        setResponses((prev) => (append ? [...prev, ...res.data.responses] : res.data.responses));
        setFilteredTotal(res.data.filtered_total ?? res.data.total);
      } catch {
        toast.error(t('errors.loadFailed'));
      }
    },
    [questionnaireId, statusFilter, t]
  );

  useEffect(() => {
    setSelected([]);
    setExpanded(null);
    load(0);
  }, [load]);

  const toggleExpand = async (responseId) => {
    if (expanded === responseId) {
      setExpanded(null);
      return;
    }
    setExpanded(responseId);
    if (!details[responseId]) {
      try {
        const res = await api.get(
          `/api/automations/questionnaires/${questionnaireId}/responses/${responseId}`
        );
        setDetails((d) => ({ ...d, [responseId]: res.data.response.answers || [] }));
      } catch {
        toast.error(t('errors.loadFailed'));
      }
    }
  };

  const toggleSelect = (responseId) => {
    setSelected((sel) =>
      sel.includes(responseId) ? sel.filter((id) => id !== responseId) : [...sel, responseId]
    );
  };

  const handleDelete = async (responseId) => {
    if (!window.confirm(t('responses.deleteConfirm'))) return;
    try {
      await api.delete(
        `/api/automations/questionnaires/${questionnaireId}/responses/${responseId}`
      );
      toast.success(t('responses.deleted'));
      load(0);
    } catch {
      toast.error(t('errors.saveFailed'));
    }
  };

  const formatAnswer = (answer) => {
    if (answer.question_type === 'multiple_choice' && answer.answer_text) {
      try {
        return JSON.parse(answer.answer_text).join(', ');
      } catch {
        return answer.answer_text;
      }
    }
    return answer.answer_text || '—';
  };

  const FILTERS = [
    { value: null, label: t('responses.filterAll') },
    { value: 'completed', label: t('responses.filterCompleted') },
    { value: 'pending', label: t('responses.filterPending') },
  ];

  return (
    <div>
      <div className="flex items-center justify-between mb-4">
        <div className="flex gap-1">
          {FILTERS.map((f) => (
            <button
              key={String(f.value)}
              onClick={() => setStatusFilter(f.value)}
              className={`px-3 py-1.5 text-xs font-medium rounded-full transition-colors ${
                statusFilter === f.value
                  ? 'bg-primary-600 text-white'
                  : 'bg-gray-100 text-gray-600 hover:bg-gray-200'
              }`}
            >
              {f.label}
            </button>
          ))}
        </div>
        <button
          onClick={() => setShowExport(true)}
          disabled={!selected.length}
          title={t('responses.selectHint')}
          className="flex items-center gap-2 px-4 py-2 bg-primary-600 text-white text-sm font-semibold rounded-button hover:bg-primary-700 transition-colors disabled:opacity-40"
        >
          <Upload className="w-4 h-4" />
          {t('responses.export')}
        </button>
      </div>

      {responses.length === 0 ? (
        <p className="text-sm text-gray-400 py-8 text-center">{t('responses.empty')}</p>
      ) : (
        <div className="border border-gray-200 rounded-card divide-y divide-gray-100 bg-white">
          {responses.map((r) => (
            <div key={r.id}>
              <div className="flex items-center gap-3 px-4 py-3">
                <input
                  type="checkbox"
                  checked={selected.includes(r.id)}
                  disabled={r.status !== 'completed'}
                  onChange={() => toggleSelect(r.id)}
                  className="w-4 h-4 rounded border-gray-300 text-primary-600 focus:ring-primary-500 disabled:opacity-30"
                />
                <div className="flex-1 min-w-0">
                  <p className="text-sm text-gray-800 truncate">
                    {r.respondent_name || r.respondent_email}
                  </p>
                  {r.completed_at && (
                    <p className="text-xs text-gray-400">
                      {new Date(r.completed_at).toLocaleString()}
                    </p>
                  )}
                </div>
                <span
                  className={`text-xs px-2 py-0.5 rounded-full font-medium ${STATUS_BADGE_CLASSES[r.status] || 'bg-gray-50 text-gray-600'}`}
                >
                  {t(`invitations.status.${r.status}`)}
                </span>
                {r.status === 'completed' && (
                  <button
                    onClick={() => toggleExpand(r.id)}
                    className="p-1 text-gray-400 hover:text-gray-600"
                  >
                    {expanded === r.id ? (
                      <ChevronUp className="w-4 h-4" />
                    ) : (
                      <ChevronDown className="w-4 h-4" />
                    )}
                  </button>
                )}
                <button
                  onClick={() => handleDelete(r.id)}
                  className="p-1 text-gray-300 hover:text-red-500"
                >
                  <Trash2 className="w-4 h-4" />
                </button>
              </div>
              {expanded === r.id && (
                <div className="px-12 pb-4 space-y-3">
                  {(details[r.id] || []).map((a) => (
                    <div key={a.question_id}>
                      <p className="text-xs font-semibold text-gray-600">{a.question_text}</p>
                      <p className="text-sm text-gray-800">{formatAnswer(a)}</p>
                    </div>
                  ))}
                </div>
              )}
            </div>
          ))}
        </div>
      )}

      {responses.length < filteredTotal && (
        <button
          onClick={() => load(responses.length, true)}
          className="mt-4 text-sm text-primary-600 hover:text-primary-700 font-medium"
        >
          {t('responses.loadMore')}
        </button>
      )}

      {showExport && (
        <ExportModal
          questionnaireId={questionnaireId}
          responseIds={selected}
          onClose={() => setShowExport(false)}
          onExported={() => {
            setSelected([]);
            load(0);
          }}
        />
      )}
    </div>
  );
}
