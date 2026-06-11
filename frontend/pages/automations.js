import { useState } from 'react';
import { Toaster } from 'react-hot-toast';
import { useTranslation } from 'next-i18next';
import { serverSideTranslations } from 'next-i18next/serverSideTranslations';
import { ClipboardList } from 'lucide-react';
import Layout from '../components/Layout';
import { useAuth } from '../hooks/useAuth';
import QuestionnairesTab from '../components/automations/questionnaire/QuestionnairesTab';

const TABS = [
  { key: 'questionnaires', labelKey: 'tabs.questionnaires', Icon: ClipboardList },
];

export default function AutomationsPage() {
  const { t } = useTranslation(['automations', 'common', 'errors']);
  const { loading: authLoading, authenticated } = useAuth();
  const [activeTab, setActiveTab] = useState('questionnaires');

  if (authLoading || !authenticated) return null;

  return (
    <Layout title={t('title')}>
      <Toaster position="top-right" />
      <div className="px-8 py-6 max-w-5xl">
        <p className="text-sm text-gray-500 mb-6">{t('subtitle')}</p>

        <div className="flex gap-1 border-b border-gray-200 mb-6">
          {TABS.map(({ key, labelKey, Icon }) => (
            <button
              key={key}
              onClick={() => setActiveTab(key)}
              className={`flex items-center gap-2 px-4 py-2 text-sm font-medium border-b-2 -mb-px transition-colors ${
                activeTab === key
                  ? 'border-primary-600 text-primary-600'
                  : 'border-transparent text-gray-500 hover:text-gray-800'
              }`}
            >
              <Icon className="w-4 h-4" />
              {t(labelKey)}
            </button>
          ))}
        </div>

        {activeTab === 'questionnaires' && <QuestionnairesTab />}
      </div>
    </Layout>
  );
}

export async function getServerSideProps({ locale }) {
  return {
    props: {
      ...(await serverSideTranslations(locale, ['automations', 'common', 'errors'])),
    },
  };
}
