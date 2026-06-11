import { useState, useEffect } from 'react';
import { useRouter } from 'next/router';
import Head from 'next/head';
import { useTranslation } from 'next-i18next';
import { serverSideTranslations } from 'next-i18next/serverSideTranslations';
import { Star, CheckCircle, Send, AlertTriangle } from 'lucide-react';
import api from '../../lib/api';

function QuestionField({ question, value, error, onChange, t }) {
  const options = question.options;

  return (
    <div className={`bg-white rounded-card border p-5 ${error ? 'border-red-300' : 'border-gray-200'}`}>
      <p className="text-sm font-semibold text-gray-800 mb-3">
        {question.question_text}
        {question.required && <span className="text-red-500 ml-1">*</span>}
      </p>

      {question.question_type === 'open' && (
        <textarea
          value={value || ''}
          onChange={(e) => onChange(e.target.value)}
          placeholder={t('form.openPlaceholder')}
          rows={3}
          className="w-full px-3 py-2 border border-gray-200 rounded-input text-sm focus:ring-2 focus:ring-primary-500 focus:border-primary-500"
        />
      )}

      {question.question_type === 'single_choice' && (
        <div className="space-y-2">
          {(options || []).map((opt) => (
            <label key={opt} className="flex items-center gap-2.5 cursor-pointer">
              <input
                type="radio"
                name={`q-${question.id}`}
                checked={value === opt}
                onChange={() => onChange(opt)}
                className="w-4 h-4 border-gray-300 text-primary-600 focus:ring-primary-500"
              />
              <span className="text-sm text-gray-700">{opt}</span>
            </label>
          ))}
        </div>
      )}

      {question.question_type === 'multiple_choice' && (
        <div className="space-y-2">
          {(options || []).map((opt) => {
            const list = Array.isArray(value) ? value : [];
            return (
              <label key={opt} className="flex items-center gap-2.5 cursor-pointer">
                <input
                  type="checkbox"
                  checked={list.includes(opt)}
                  onChange={() =>
                    onChange(
                      list.includes(opt) ? list.filter((v) => v !== opt) : [...list, opt]
                    )
                  }
                  className="w-4 h-4 rounded border-gray-300 text-primary-600 focus:ring-primary-500"
                />
                <span className="text-sm text-gray-700">{opt}</span>
              </label>
            );
          })}
        </div>
      )}

      {question.question_type === 'rating' && (
        <div className="flex items-center gap-1">
          {(() => {
            const min = options?.min ?? 1;
            const max = options?.max ?? 5;
            return Array.from({ length: max - min + 1 }, (_, i) => min + i).map((n) => (
              <button key={n} type="button" onClick={() => onChange(n)} className="p-0.5">
                <Star
                  className={`w-7 h-7 transition-colors ${
                    value != null && n <= value
                      ? 'text-yellow-400 fill-yellow-400'
                      : 'text-gray-200'
                  }`}
                />
              </button>
            ));
          })()}
        </div>
      )}

      {error && <p className="text-xs text-red-500 mt-2">{t('form.required')}</p>}
    </div>
  );
}

export default function PublicQuestionnairePage() {
  const router = useRouter();
  const { token } = router.query;
  const { t } = useTranslation('questionnaire');

  // loading | form | completed | success | notFound | error
  const [state, setState] = useState('loading');
  const [questionnaire, setQuestionnaire] = useState(null);
  const [answers, setAnswers] = useState({});
  const [errors, setErrors] = useState({});
  const [respondentName, setRespondentName] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState(false);

  useEffect(() => {
    if (!token) return;
    api
      .get(`/questionnaire/${token}`)
      .then((res) => {
        if (res.data.completed) {
          setState('completed');
        } else {
          setQuestionnaire(res.data);
          setState('form');
        }
      })
      .catch((err) => setState(err.response?.status === 404 ? 'notFound' : 'error'));
  }, [token]);

  const setAnswer = (questionId, value) => {
    setAnswers((a) => ({ ...a, [questionId]: value }));
    setErrors((e) => ({ ...e, [questionId]: false }));
  };

  const submit = async () => {
    const missing = {};
    for (const q of questionnaire.questions) {
      const v = answers[q.id];
      if (q.required && (v === undefined || v === '' || (Array.isArray(v) && !v.length))) {
        missing[q.id] = true;
      }
    }
    if (Object.keys(missing).length) {
      setErrors(missing);
      return;
    }
    setSubmitting(true);
    setSubmitError(false);
    try {
      await api.post(`/questionnaire/${token}/submit`, {
        respondent_name: respondentName.trim() || null,
        answers: Object.entries(answers).map(([qid, value]) => ({
          question_id: parseInt(qid, 10),
          value,
        })),
      });
      setState('success');
    } catch (err) {
      if (err.response?.status === 409) setState('completed');
      else setSubmitError(true);
    } finally {
      setSubmitting(false);
    }
  };

  const Shell = ({ children }) => (
    <div className="min-h-screen bg-slate-50 py-10 px-4">
      <Head>
        <title>{questionnaire?.title || 'Questionnaire'} — TAIC</title>
      </Head>
      <div className="max-w-2xl mx-auto">{children}</div>
    </div>
  );

  const CenteredMessage = ({ icon, text }) => (
    <div className="bg-white rounded-card border border-gray-200 p-10 text-center">
      {icon}
      <p className="text-sm text-gray-600">{text}</p>
    </div>
  );

  if (state === 'loading') {
    return (
      <Shell>
        <CenteredMessage icon={null} text={t('loading')} />
      </Shell>
    );
  }
  if (state === 'notFound' || state === 'error') {
    return (
      <Shell>
        <CenteredMessage
          icon={<AlertTriangle className="w-10 h-10 text-amber-400 mx-auto mb-3" />}
          text={state === 'notFound' ? t('notFound') : t('error')}
        />
      </Shell>
    );
  }
  if (state === 'completed') {
    return (
      <Shell>
        <CenteredMessage
          icon={<CheckCircle className="w-10 h-10 text-green-500 mx-auto mb-3" />}
          text={t('alreadyCompleted')}
        />
      </Shell>
    );
  }
  if (state === 'success') {
    return (
      <Shell>
        <div className="bg-white rounded-card border border-gray-200 p-10 text-center">
          <CheckCircle className="w-12 h-12 text-green-500 mx-auto mb-4" />
          <h1 className="text-lg font-bold text-gray-900 mb-2">{t('success.title')}</h1>
          <p className="text-sm text-gray-500">{t('success.message')}</p>
        </div>
      </Shell>
    );
  }

  return (
    <Shell>
      <div className="mb-6">
        <h1 className="text-2xl font-bold text-gray-900 mb-1">{questionnaire.title}</h1>
        {questionnaire.description && (
          <p className="text-sm text-gray-500">{questionnaire.description}</p>
        )}
      </div>

      <div className="bg-white rounded-card border border-gray-200 p-5 mb-4">
        <label className="block text-sm font-medium text-gray-700 mb-1.5">
          {t('form.nameLabel')}
        </label>
        <input
          type="text"
          value={respondentName}
          onChange={(e) => setRespondentName(e.target.value)}
          placeholder={t('form.namePlaceholder')}
          className="w-full px-3 py-2 border border-gray-200 rounded-input text-sm focus:ring-2 focus:ring-primary-500 focus:border-primary-500"
        />
      </div>

      <div className="space-y-4">
        {questionnaire.questions.map((q) => (
          <QuestionField
            key={q.id}
            question={q}
            value={answers[q.id]}
            error={errors[q.id]}
            onChange={(v) => setAnswer(q.id, v)}
            t={t}
          />
        ))}
      </div>

      {submitError && (
        <div className="flex items-center gap-2 mt-4 px-4 py-3 bg-red-50 border border-red-200 rounded-card text-sm text-red-700">
          <AlertTriangle className="w-4 h-4 shrink-0" />
          {t('error')}
        </div>
      )}

      <button
        onClick={submit}
        disabled={submitting}
        className="mt-6 w-full flex items-center justify-center gap-2 px-5 py-3 bg-primary-600 text-white text-sm font-semibold rounded-button hover:bg-primary-700 transition-colors disabled:opacity-50"
      >
        <Send className="w-4 h-4" />
        {submitting ? t('form.submitting') : t('form.submit')}
      </button>
    </Shell>
  );
}

export async function getServerSideProps({ locale }) {
  return {
    props: {
      ...(await serverSideTranslations(locale, ['questionnaire'])),
    },
  };
}
