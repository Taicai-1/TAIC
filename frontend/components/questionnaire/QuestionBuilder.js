import { useState, useEffect } from 'react';
import { useTranslation } from 'next-i18next';
import { Plus, ClipboardList } from 'lucide-react';
import QuestionCard from './QuestionCard';
import api from '../../lib/api';
import toast from 'react-hot-toast';

export default function QuestionBuilder({ agentId, welcomeMessage, closingMessage, onWelcomeChange, onClosingChange }) {
  const { t } = useTranslation('questionnaire');
  const [questions, setQuestions] = useState([]);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (agentId) loadQuestions();
  }, [agentId]);

  const loadQuestions = async () => {
    try {
      setLoading(true);
      const res = await api.get(`/api/agents/${agentId}/questions`);
      setQuestions(res.data);
    } catch (err) {
      console.error('Failed to load questions:', err);
    } finally {
      setLoading(false);
    }
  };

  const addQuestion = async () => {
    try {
      const res = await api.post(`/api/agents/${agentId}/questions`, {
        question_text: '',
        question_type: 'open',
        required: true,
      });
      setQuestions([...questions, res.data]);
    } catch (err) {
      toast.error('Failed to add question');
    }
  };

  const updateQuestion = async (index, updated) => {
    const q = updated;
    try {
      await api.patch(`/api/agents/${agentId}/questions/${q.id}`, {
        question_text: q.question_text,
        question_type: q.question_type,
        options: q.options,
        required: q.required,
      });
      const next = [...questions];
      next[index] = q;
      setQuestions(next);
    } catch (err) {
      toast.error('Failed to update question');
    }
  };

  const deleteQuestion = async (index) => {
    const q = questions[index];
    try {
      await api.delete(`/api/agents/${agentId}/questions/${q.id}`);
      setQuestions(questions.filter((_, i) => i !== index));
    } catch (err) {
      toast.error('Failed to delete question');
    }
  };

  return (
    <div className="space-y-6">
      {/* Welcome message */}
      <div>
        <label className="block text-sm font-semibold text-gray-700 mb-2">{t('builder.welcomeMessage')}</label>
        <input
          type="text"
          value={welcomeMessage || ''}
          onChange={(e) => onWelcomeChange(e.target.value)}
          placeholder={t('builder.welcomePlaceholder')}
          className="w-full px-4 py-2.5 border border-gray-200 rounded-input text-sm focus:ring-2 focus:ring-primary-500 focus:border-primary-500"
        />
      </div>

      {/* Questions list */}
      <div>
        <h3 className="text-sm font-semibold text-gray-700 mb-3 flex items-center gap-2">
          <ClipboardList className="w-4 h-4 text-primary-600" />
          {t('builder.title')} ({questions.length})
        </h3>
        {questions.length === 0 && !loading ? (
          <div className="text-center py-8 border-2 border-dashed border-gray-200 rounded-card">
            <ClipboardList className="w-10 h-10 text-gray-300 mx-auto mb-2" />
            <p className="text-sm text-gray-500">{t('builder.noQuestions')}</p>
          </div>
        ) : (
          <div className="space-y-3">
            {questions.map((q, idx) => (
              <QuestionCard
                key={q.id}
                question={q}
                index={idx}
                onChange={(updated) => updateQuestion(idx, updated)}
                onDelete={() => deleteQuestion(idx)}
              />
            ))}
          </div>
        )}
        <button
          onClick={addQuestion}
          className="mt-3 flex items-center gap-2 px-4 py-2.5 text-sm font-medium text-primary-600 border border-primary-200 rounded-button hover:bg-primary-50 transition-colors w-full justify-center"
        >
          <Plus className="w-4 h-4" />
          {t('builder.addQuestion')}
        </button>
      </div>

      {/* Closing message */}
      <div>
        <label className="block text-sm font-semibold text-gray-700 mb-2">{t('builder.closingMessage')}</label>
        <input
          type="text"
          value={closingMessage || ''}
          onChange={(e) => onClosingChange(e.target.value)}
          placeholder={t('builder.closingPlaceholder')}
          className="w-full px-4 py-2.5 border border-gray-200 rounded-input text-sm focus:ring-2 focus:ring-primary-500 focus:border-primary-500"
        />
      </div>
    </div>
  );
}
