import { useRouter } from 'next/router';
import { useEffect, useState } from 'react';
import toast from 'react-hot-toast';
import { useTranslation } from 'next-i18next';
import { serverSideTranslations } from 'next-i18next/serverSideTranslations';
import { Users, UserCircle, Zap, Loader2 } from 'lucide-react';
import Layout from '../../components/Layout';
import { useAuth } from '../../hooks/useAuth';
import api from '../../lib/api';

export default function TeamView() {
  const router = useRouter();
  const { id } = router.query;
  const { t } = useTranslation(['teams', 'common', 'errors']);
  const { user, loading: authLoading, authenticated } = useAuth();
  const [team, setTeam] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!id || !authenticated) return;
    loadTeam(id);
    // eslint-disable-next-line
  }, [id, authenticated]);

  const loadTeam = async (teamId) => {
    try {
      const res = await api.get(`/teams/${teamId}`);
      setTeam(res.data.team || res.data);
    } catch (e) {
      console.error(e);
      toast.error(t('teams:detail.loadError'));
    } finally {
      setLoading(false);
    }
  };

  if (authLoading || loading) return (
    <div className="min-h-screen bg-gray-50 flex items-center justify-center">
      <Loader2 className="w-8 h-8 text-primary-600 animate-spin" />
    </div>
  );

  if (!team) return (
    <div className="min-h-screen bg-gray-50 flex items-center justify-center">
      <p className="text-gray-500">{t('teams:detail.notFound')}</p>
    </div>
  );

  return (
    <Layout showBack backHref="/teams" title={team.name}>
      <div className="py-8 px-4 sm:px-6 lg:px-8">
        <div className="max-w-3xl mx-auto">
          <div className="bg-white rounded-card shadow-card border border-gray-200 p-8 animate-fade-in">
            <div className="flex items-center space-x-4 mb-8">
              <div className="w-14 h-14 rounded-card bg-gradient-to-br from-purple-500 to-blue-500 flex items-center justify-center shadow-card">
                <Users className="w-7 h-7 text-white" />
              </div>
              <div>
                <h2 className="text-2xl font-heading font-bold text-gray-900">{team.name}</h2>
                {team.contexte && (
                  <p className="text-sm text-gray-500 mt-1">{team.contexte}</p>
                )}
              </div>
            </div>

            <div className="space-y-6">
              <div className="p-4 bg-gray-50 rounded-button border border-gray-100">
                <div className="flex items-center space-x-2 mb-2">
                  <UserCircle className="w-5 h-5 text-primary-600" />
                  <span className="text-sm font-semibold text-gray-700">{t('teams:detail.leaderAgent')}</span>
                </div>
                <p className="text-base font-medium text-gray-900 ml-7">{team.leader_name || team.leader_agent_id}</p>
              </div>

              <div>
                <div className="flex items-center space-x-2 mb-3">
                  <Zap className="w-5 h-5 text-purple-600" />
                  <span className="text-sm font-semibold text-gray-700">{t('teams:detail.actionableAgents')}</span>
                </div>
                <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                  {(team.action_agent_names || []).map((n, i) => (
                    <div key={i} className="p-3 bg-white border border-gray-200 rounded-button shadow-subtle hover:shadow-card transition-all">
                      <span className="text-sm font-medium text-gray-800">{n}</span>
                    </div>
                  ))}
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </Layout>
  );
}

export async function getServerSideProps({ locale }) {
  return {
    props: {
      ...(await serverSideTranslations(locale, ['teams', 'common', 'errors'])),
    },
  };
}
