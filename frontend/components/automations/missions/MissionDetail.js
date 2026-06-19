import { useState, useEffect, useCallback } from 'react';
import { useTranslation } from 'next-i18next';
import toast from 'react-hot-toast';
import { ArrowLeft } from 'lucide-react';
import api from '../../../lib/api';
import PlanningTab from './PlanningTab';
import DocumentsTab from './DocumentsTab';
import RecapsTab from './RecapsTab';
import ChatTab from './ChatTab';
import SettingsTab from './SettingsTab';

const SUB_TABS = ['planning', 'documents', 'recaps', 'chat', 'settings'];

export default function MissionDetail({ missionId, onBack }) {
  const { t } = useTranslation('automations');
  const [mission, setMission] = useState(null);
  const [subTab, setSubTab] = useState('planning');

  const load = useCallback(async () => {
    try {
      const res = await api.get(`/api/automations/missions/${missionId}`);
      setMission(res.data.mission);
    } catch {
      toast.error(t('errors.loadFailed'));
      onBack?.();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [missionId]);

  useEffect(() => {
    load();
  }, [load]);

  if (!mission) {
    return <div className="py-16 text-center text-sm text-gray-400">…</div>;
  }

  return (
    <div>
      <button
        onClick={onBack}
        className="flex items-center gap-1.5 text-sm text-gray-500 hover:text-gray-800 mb-4 transition-colors"
      >
        <ArrowLeft className="w-4 h-4" />
        {t('missions.detail.back')}
      </button>

      <h2 className="text-xl font-bold text-gray-900 mb-1">{mission.name}</h2>
      <p className="text-sm text-gray-500 mb-4">{mission.objective}</p>

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
            {t(`missions.detail.tabs.${key}`)}
          </button>
        ))}
      </div>

      {subTab === 'planning' && <PlanningTab missionId={mission.id} />}
      {subTab === 'documents' && <DocumentsTab missionId={mission.id} />}
      {subTab === 'recaps' && <RecapsTab missionId={mission.id} hasCompanion={!!mission.agent_id} />}
      {subTab === 'chat' && <ChatTab missionId={mission.id} hasCompanion={!!mission.agent_id} />}
      {subTab === 'settings' && <SettingsTab mission={mission} onChanged={load} onDeleted={onBack} />}
    </div>
  );
}
