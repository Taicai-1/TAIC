import { useState, useEffect, useCallback } from 'react';
import { useRouter } from 'next/router';
import { useTranslation } from 'next-i18next';
import toast from 'react-hot-toast';
import api from '../../../lib/api';
import MissionList from './MissionList';
import MissionEditor from './MissionEditor';
import MissionDetail from './MissionDetail';

export default function MissionsTab() {
  const { t } = useTranslation('automations');
  const router = useRouter();
  const [missions, setMissions] = useState([]);
  const [loading, setLoading] = useState(true);

  const selectedId = router.query.mission ? parseInt(router.query.mission, 10) : null;
  const creating = router.query.createMission === '1';

  const load = useCallback(async () => {
    try {
      const res = await api.get('/api/automations/missions');
      setMissions(res.data.missions || []);
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
    if (!window.confirm(t('missions.list.deleteConfirm'))) return;
    try {
      await api.delete(`/api/automations/missions/${id}`);
      toast.success(t('missions.list.deleted'));
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
      <MissionEditor
        onSaved={(m) => {
          load();
          setQuery({ mission: m.id });
        }}
        onCancel={() => setQuery({})}
      />
    );
  }

  if (selectedId) {
    return (
      <MissionDetail
        missionId={selectedId}
        onBack={() => {
          load();
          setQuery({});
        }}
      />
    );
  }

  return (
    <MissionList
      missions={missions}
      onOpen={(id) => setQuery({ mission: id })}
      onCreate={() => setQuery({ createMission: '1' })}
      onDelete={handleDelete}
    />
  );
}
