import { useState, useEffect } from 'react';
import { useTranslation } from 'next-i18next';
import { Download, Upload, ArrowLeft, Star, Loader2 } from 'lucide-react';
import api, { getApiUrl } from '../../lib/api';
import ExportModal from './ExportModal';

const STATUS_COLORS = {
  pending: 'bg-yellow-100 text-yellow-700',
  in_progress: 'bg-blue-100 text-blue-700',
  completed: 'bg-green-100 text-green-700',
};

export default function ResponsesTab({ agentId }) {
  const { t } = useTranslation('questionnaire');
  const [responses, setResponses] = useState([]);
  const [stats, setStats] = useState({ total_invited: 0, total_completed: 0 });
  const [filter, setFilter] = useState(null);
  const [selectedDetail, setSelectedDetail] = useState(null);
  const [detailData, setDetailData] = useState(null);
  const [selectedIds, setSelectedIds] = useState([]);
  const [showExportModal, setShowExportModal] = useState(false);

  useEffect(() => {
    if (agentId) loadResponses();
  }, [agentId, filter]);

  const loadResponses = async () => {
    try {
      const params = filter ? `?status=${filter}` : '';
      const res = await api.get(`/api/agents/${agentId}/responses${params}`);
      setResponses(res.data.responses);
      setStats({ total_invited: res.data.total_invited, total_completed: res.data.total_completed });
    } catch (err) {
      console.error('Failed to load responses:', err);
    }
  };

  const loadDetail = async (responseId) => {
    try {
      const res = await api.get(`/api/agents/${agentId}/responses/${responseId}`);
      setDetailData(res.data);
      setSelectedDetail(responseId);
    } catch (err) {
      console.error('Failed to load response detail:', err);
    }
  };

  const toggleSelect = (id) => {
    setSelectedIds((prev) =>
      prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id]
    );
  };

  const downloadPdf = (responseId) => {
    window.open(`${getApiUrl()}/api/agents/${agentId}/responses/${responseId}/pdf`, '_blank');
  };

  // Detail view
  if (selectedDetail && detailData) {
    return (
      <div className="space-y-4">
        <button onClick={() => { setSelectedDetail(null); setDetailData(null); }} className="flex items-center gap-1 text-sm text-primary-600 hover:text-primary-700">
          <ArrowLeft className="w-4 h-4" />
          {t('responses.backToList')}
        </button>
        <div className="bg-white border border-gray-200 rounded-card p-5">
          <div className="flex items-center justify-between mb-4">
            <div>
              <h3 className="text-lg font-semibold text-gray-900">{detailData.respondent_name || detailData.respondent_email}</h3>
              {detailData.respondent_name && <p className="text-sm text-gray-500">{detailData.respondent_email}</p>}
            </div>
            <div className="flex gap-2">
              <button onClick={() => downloadPdf(detailData.id)} className="flex items-center gap-1.5 px-3 py-1.5 text-sm border border-gray-200 rounded-button hover:bg-gray-50">
                <Download className="w-4 h-4" />
                {t('responses.downloadPdf')}
              </button>
              <button onClick={() => { setSelectedIds([detailData.id]); setShowExportModal(true); }} className="flex items-center gap-1.5 px-3 py-1.5 text-sm bg-primary-600 text-white rounded-button hover:bg-primary-700">
                <Upload className="w-4 h-4" />
                {t('responses.exportToAgent')}
              </button>
            </div>
          </div>
          <div className="space-y-4">
            {detailData.answers.map((ans) => (
              <div key={ans.id} className="border-b border-gray-100 pb-3">
                <p className="text-sm font-semibold text-gray-700 mb-1">{ans.question_text}</p>
                {ans.question_type === 'rating' ? (
                  <div className="flex items-center gap-1">
                    {Array.from({ length: parseInt(ans.answer_text) || 0 }, (_, i) => (
                      <Star key={i} className="w-4 h-4 text-yellow-400 fill-yellow-400" />
                    ))}
                    <span className="text-sm text-gray-500 ml-2">{ans.answer_text}</span>
                  </div>
                ) : (
                  <p className="text-sm text-gray-600">{ans.answer_text}</p>
                )}
              </div>
            ))}
          </div>
        </div>
        {showExportModal && (
          <ExportModal agentId={agentId} responseIds={selectedIds} onClose={() => setShowExportModal(false)} />
        )}
      </div>
    );
  }

  // List view
  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <p className="text-sm text-gray-600">
          {t('responses.counter', { completed: stats.total_completed, total: stats.total_invited })}
        </p>
        <div className="flex gap-2">
          {selectedIds.length > 0 && (
            <button onClick={() => setShowExportModal(true)} className="flex items-center gap-1.5 px-3 py-1.5 text-sm bg-primary-600 text-white rounded-button hover:bg-primary-700">
              <Upload className="w-4 h-4" />
              {t('responses.exportToAgent')} ({selectedIds.length})
            </button>
          )}
        </div>
      </div>
      {/* Filters */}
      <div className="flex gap-2">
        {[null, 'completed', 'pending'].map((f) => (
          <button
            key={f || 'all'}
            onClick={() => setFilter(f)}
            className={`px-3 py-1.5 text-sm rounded-button font-medium transition-colors ${
              filter === f ? 'bg-primary-600 text-white' : 'bg-gray-100 text-gray-600 hover:bg-gray-200'
            }`}
          >
            {f === null ? t('responses.filterAll') : t(`responses.filter${f.charAt(0).toUpperCase() + f.slice(1)}`)}
          </button>
        ))}
      </div>
      {/* Response list */}
      {responses.length === 0 ? (
        <div className="text-center py-12 text-gray-500 text-sm">{t('responses.noResponses')}</div>
      ) : (
        <div className="bg-white border border-gray-200 rounded-card overflow-hidden divide-y divide-gray-100">
          {responses.map((r) => (
            <div key={r.id} className="flex items-center px-5 py-3 hover:bg-gray-50 cursor-pointer" onClick={() => r.status === 'completed' && loadDetail(r.id)}>
              <input
                type="checkbox"
                checked={selectedIds.includes(r.id)}
                onChange={(e) => { e.stopPropagation(); toggleSelect(r.id); }}
                className="mr-3 rounded border-gray-300 text-primary-600 focus:ring-primary-500"
                disabled={r.status !== 'completed'}
              />
              <div className="flex-1 min-w-0">
                <p className="text-sm font-medium text-gray-800 truncate">{r.respondent_name || r.respondent_email}</p>
                {r.respondent_name && <p className="text-xs text-gray-500">{r.respondent_email}</p>}
              </div>
              {r.completed_at && (
                <span className="text-xs text-gray-400 mr-3">
                  {new Date(r.completed_at).toLocaleDateString('fr-FR')}
                </span>
              )}
              <span className={`px-2.5 py-0.5 text-xs font-medium rounded-full ${STATUS_COLORS[r.status]}`}>
                {t(`invitations.status.${r.status}`)}
              </span>
            </div>
          ))}
        </div>
      )}
      {showExportModal && (
        <ExportModal agentId={agentId} responseIds={selectedIds} onClose={() => { setShowExportModal(false); setSelectedIds([]); }} />
      )}
    </div>
  );
}
