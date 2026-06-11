import { useState, useEffect, useCallback } from 'react';
import { useTranslation } from 'next-i18next';
import toast from 'react-hot-toast';
import { ArrowLeft } from 'lucide-react';
import api from '../../../lib/api';
import QuestionnaireEditor from './QuestionnaireEditor';
import InvitationsTab from './InvitationsTab';
import ResponsesTab from './ResponsesTab';

const SUB_TABS = ['questions', 'invitations', 'responses'];

export default function QuestionnaireDetail({ questionnaireId, onBack }) {
  const { t } = useTranslation('automations');
  const [questionnaire, setQuestionnaire] = useState(null);
  const [subTab, setSubTab] = useState('questions');

  const load = useCallback(async () => {
    try {
      const res = await api.get(`/api/automations/questionnaires/${questionnaireId}`);
      setQuestionnaire(res.data.questionnaire);
    } catch {
      toast.error(t('errors.loadFailed'));
      onBack?.();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [questionnaireId]);

  useEffect(() => {
    load();
  }, [load]);

  if (!questionnaire) {
    return <div className="py-16 text-center text-sm text-gray-400">…</div>;
  }

  return (
    <div>
      <button
        onClick={onBack}
        className="flex items-center gap-1.5 text-sm text-gray-500 hover:text-gray-800 mb-4 transition-colors"
      >
        <ArrowLeft className="w-4 h-4" />
        {t('detail.back')}
      </button>

      <h2 className="text-xl font-bold text-gray-900 mb-4">{questionnaire.title}</h2>

      <div className="flex gap-1 border-b border-gray-200 mb-6">
        {SUB_TABS.map((key) => (
          <button
            key={key}
            onClick={() => setSubTab(key)}
            className={`px-4 py-2 text-sm font-medium border-b-2 -mb-px transition-colors ${
              subTab === key
                ? 'border-primary-600 text-primary-600'
                : 'border-transparent text-gray-500 hover:text-gray-800'
            }`}
          >
            {t(`detail.tabs.${key}`)}
          </button>
        ))}
      </div>

      {subTab === 'questions' && (
        <QuestionnaireEditor questionnaire={questionnaire} onSaved={() => load()} />
      )}
      {subTab === 'invitations' && <InvitationsTab questionnaireId={questionnaire.id} />}
      {subTab === 'responses' && <ResponsesTab questionnaireId={questionnaire.id} />}
    </div>
  );
}
