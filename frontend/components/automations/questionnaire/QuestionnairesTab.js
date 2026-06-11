import { useState, useEffect, useCallback } from 'react';
import { useRouter } from 'next/router';
import { useTranslation } from 'next-i18next';
import toast from 'react-hot-toast';
import api from '../../../lib/api';
import QuestionnaireList from './QuestionnaireList';
import QuestionnaireEditor from './QuestionnaireEditor';
import QuestionnaireDetail from './QuestionnaireDetail';

export default function QuestionnairesTab() {
  const { t } = useTranslation('automations');
  const router = useRouter();
  const [questionnaires, setQuestionnaires] = useState([]);
  const [loading, setLoading] = useState(true);

  const selectedId = router.query.questionnaire
    ? parseInt(router.query.questionnaire, 10)
    : null;
  const creating = router.query.create === '1';

  const load = useCallback(async () => {
    try {
      const res = await api.get('/api/automations/questionnaires');
      setQuestionnaires(res.data.questionnaires || []);
    } catch {
      toast.error(t('errors.loadFailed'));
    } finally {
      setLoading(false);
    }
  }, [t]);

  useEffect(() => {
    load();
  }, [load]);

  const setQuery = (query) =>
    router.push({ pathname: '/automations', query }, undefined, { shallow: true });

  const handleDelete = async (id) => {
    if (!window.confirm(t('list.deleteConfirm'))) return;
    try {
      await api.delete(`/api/automations/questionnaires/${id}`);
      toast.success(t('list.deleted'));
      load();
    } catch {
      toast.error(t('errors.saveFailed'));
    }
  };

  if (loading) {
    return <div className="py-16 text-center text-sm text-gray-400">…</div>;
  }

  if (creating) {
    return (
      <QuestionnaireEditor
        onSaved={(q) => {
          load();
          setQuery({ questionnaire: q.id });
        }}
        onCancel={() => setQuery({})}
      />
    );
  }

  if (selectedId) {
    return (
      <QuestionnaireDetail
        questionnaireId={selectedId}
        onBack={() => {
          load();
          setQuery({});
        }}
      />
    );
  }

  return (
    <QuestionnaireList
      questionnaires={questionnaires}
      onOpen={(id) => setQuery({ questionnaire: id })}
      onCreate={() => setQuery({ create: '1' })}
      onDelete={handleDelete}
    />
  );
}
