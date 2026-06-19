import { useState } from 'react';
import { useTranslation } from 'next-i18next';
import toast from 'react-hot-toast';
import { Plus, Save, Lock } from 'lucide-react';
import api from '../../../lib/api';
import QuestionCard from './QuestionCard';

export default function QuestionnaireEditor({ questionnaire = null, onSaved, onCancel }) {
  const { t } = useTranslation('automations');
  const isEdit = Boolean(questionnaire?.id);
  const locked = isEdit && (questionnaire.completed_count || 0) > 0;

  const [title, setTitle] = useState(questionnaire?.title || '');
  const [description, setDescription] = useState(questionnaire?.description || '');
  const [questions, setQuestions] = useState(
    (questionnaire?.questions || []).map((q) => ({
      ...q,
      options:
        q.options != null && typeof q.options !== 'string'
          ? JSON.stringify(q.options)
          : q.options,
    }))
  );
  const [saving, setSaving] = useState(false);

  const addQuestion = () =>
    setQuestions((qs) => [
      ...qs,
      { question_text: '', question_type: 'open', options: null, required: true },
    ]);
  const updateQuestion = (idx, next) =>
    setQuestions((qs) => qs.map((q, i) => (i === idx ? next : q)));
  const deleteQuestion = (idx) => setQuestions((qs) => qs.filter((_, i) => i !== idx));

  const save = async () => {
    if (!title.trim()) {
      toast.error(t('editor.titleRequired'));
      return;
    }
    if (!questions.length || questions.some((q) => !q.question_text.trim())) {
      toast.error(questions.length ? t('editor.questionTextRequired') : t('editor.noQuestions'));
      return;
    }
    const payload = {
      title: title.trim(),
      description: description.trim() || null,
      questions: questions.map((q, idx) => ({
        question_text: q.question_text.trim(),
        question_type: q.question_type,
        options: q.options ? JSON.parse(q.options) : null,
        position: idx,
        required: Boolean(q.required),
      })),
    };
    setSaving(true);
    try {
      const res = isEdit
        ? await api.put(`/api/automations/questionnaires/${questionnaire.id}`, payload)
        : await api.post('/api/automations/questionnaires', payload);
      toast.success(t('editor.saved'));
      onSaved?.(res.data.questionnaire);
    } catch (err) {
      const detail = err.response?.data?.detail;
      toast.error(typeof detail === 'string' ? detail : t('errors.saveFailed'));
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="space-y-5">
      {!isEdit && <h2 className="text-lg font-bold text-gray-900">{t('editor.createTitle')}</h2>}

      {locked && (
        <div className="flex items-center gap-2 px-4 py-3 bg-amber-50 border border-amber-200 rounded-card text-sm text-amber-800">
          <Lock className="w-4 h-4 shrink-0" />
          {t('editor.lockedByResponses')}
        </div>
      )}

      <div>
        <label className="block text-sm font-medium text-gray-700 mb-1.5">{t('editor.titleLabel')}</label>
        <input
          type="text"
          value={title}
          disabled={locked}
          onChange={(e) => setTitle(e.target.value)}
          placeholder={t('editor.titlePlaceholder')}
          className="w-full px-3 py-2 border border-gray-200 rounded-input text-sm focus:ring-2 focus:ring-primary-500 focus:border-primary-500 disabled:bg-gray-50"
        />
      </div>

      <div>
        <label className="block text-sm font-medium text-gray-700 mb-1.5">{t('editor.descriptionLabel')}</label>
        <textarea
          value={description}
          disabled={locked}
          onChange={(e) => setDescription(e.target.value)}
          placeholder={t('editor.descriptionPlaceholder')}
          rows={3}
          className="w-full px-3 py-2 border border-gray-200 rounded-input text-sm focus:ring-2 focus:ring-primary-500 focus:border-primary-500 disabled:bg-gray-50"
        />
      </div>

      <div>
        <h3 className="text-sm font-semibold text-gray-800 mb-3">{t('editor.questionsTitle')}</h3>
        {questions.length === 0 && (
          <p className="text-sm text-gray-400 mb-3">{t('editor.noQuestions')}</p>
        )}
        <div className="space-y-3">
          {questions.map((q, idx) => (
            <QuestionCard
              key={q.id ?? `new-${idx}`}
              question={q}
              index={idx}
              disabled={locked}
              onChange={(next) => updateQuestion(idx, next)}
              onDelete={() => deleteQuestion(idx)}
            />
          ))}
        </div>
        {!locked && (
          <button
            onClick={addQuestion}
            className="mt-3 flex items-center gap-1.5 text-sm text-primary-600 hover:text-primary-700 font-medium"
          >
            <Plus className="w-4 h-4" />
            {t('editor.addQuestion')}
          </button>
        )}
      </div>

      <div className="flex items-center gap-3 pt-2">
        {!locked && (
          <button
            onClick={save}
            disabled={saving}
            className="flex items-center gap-2 px-5 py-2.5 bg-primary-600 text-white text-sm font-semibold rounded-button hover:bg-primary-700 transition-colors disabled:opacity-50"
          >
            <Save className="w-4 h-4" />
            {t('editor.save')}
          </button>
        )}
        {onCancel && (
          <button
            onClick={onCancel}
            className="px-5 py-2.5 text-sm font-medium text-gray-600 hover:text-gray-800"
          >
            {t('editor.cancel')}
          </button>
        )}
      </div>
    </div>
  );
}
