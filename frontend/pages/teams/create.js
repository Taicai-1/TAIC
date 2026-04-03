import { useState, useEffect } from "react";
import { useRouter } from "next/router";
import toast, { Toaster } from "react-hot-toast";
import { useTranslation } from 'next-i18next';
import { serverSideTranslations } from 'next-i18next/serverSideTranslations';
import { Users, Zap, UserCircle, CheckCircle2, Loader2 } from 'lucide-react';
import Layout from '../../components/Layout';
import { useAuth } from '../../hooks/useAuth';
import api from '../../lib/api';

export default function CreateTeamPage() {
  const { t } = useTranslation(['teams', 'common', 'errors']);
  const router = useRouter();
  const { user, loading: authLoading, authenticated } = useAuth();
  const [agents, setAgents] = useState([]);
  const [loading, setLoading] = useState(true);
  const [creating, setCreating] = useState(false);
  const [name, setName] = useState("");
  const [contexte, setContexte] = useState("");
  const [leaderId, setLeaderId] = useState(null);
  const [actionIds, setActionIds] = useState([]);

  useEffect(() => {
    if (!authenticated) return;
    loadAgents();
    // eslint-disable-next-line
  }, [authenticated]);

  const loadAgents = async () => {
    try {
      const res = await api.get('/agents');
      setAgents(res.data.agents || []);
    } catch (e) {
      console.error(e);
      toast.error(t('teams:errors.loadingAgents'));
    } finally {
      setLoading(false);
    }
  };

  const toggleActionAgent = (id) => {
    setActionIds(prev => {
      if (prev.includes(id)) return prev.filter(x => x !== id);
      return [...prev, id];
    });
  };

  const submit = async () => {
    if (!name.trim()) { toast.error(t('teams:errors.nameRequired')); return; }
    if (!leaderId) { toast.error(t('teams:errors.leaderRequired')); return; }
    setCreating(true);
    try {
      const payload = { name, contexte, leader_agent_id: leaderId, action_agent_ids: actionIds };
      const res = await api.post('/teams', payload);
      toast.success(t('teams:success.teamCreated'));
      const id = res.data.team && res.data.team.id;
      router.push(id ? `/teams/${id}` : '/teams');
    } catch (e) {
      console.error(e);
      toast.error(t('teams:errors.creatingTeam'));
    } finally {
      setCreating(false);
    }
  };

  const convAgents = agents.filter(a => (a.type || 'conversationnel') === 'conversationnel');
  const actionAgentsList = agents.filter(a => a.type === 'actionnable');

  if (authLoading || loading) return (
    <div className="min-h-screen bg-gray-50 flex items-center justify-center">
      <Loader2 className="w-8 h-8 text-blue-600 animate-spin" />
    </div>
  );

  return (
    <Layout showBack backHref="/teams" title={t('teams:form.title')}>
      <Toaster position="top-right" />

      <div className="py-8 px-4 sm:px-6 lg:px-8">
        <div className="max-w-3xl mx-auto">
          <div className="bg-white rounded-card shadow-card border border-gray-200 p-8 animate-fade-in">
            <div className="flex items-center space-x-3 mb-8">
              <div className="w-10 h-10 rounded-button bg-gradient-to-br from-purple-500 to-blue-500 flex items-center justify-center">
                <Users className="w-5 h-5 text-white" />
              </div>
              <h2 className="text-2xl font-heading font-bold text-gray-900">{t('teams:form.title')}</h2>
            </div>

            <div className="space-y-6">
              <div>
                <label className="text-sm font-medium text-gray-700 mb-2 block">{t('teams:form.teamName')}</label>
                <input
                  value={name}
                  onChange={e => setName(e.target.value)}
                  className="w-full px-4 py-3 border border-gray-200 rounded-input focus:border-blue-500 focus:ring-2 focus:ring-blue-200 transition-all outline-none bg-white"
                  placeholder={t('teams:form.teamName')}
                />
              </div>

              <div>
                <label className="text-sm font-medium text-gray-700 mb-2 block">{t('teams:form.teamContext')}</label>
                <textarea
                  value={contexte}
                  onChange={e => setContexte(e.target.value)}
                  className="w-full px-4 py-3 border border-gray-200 rounded-input focus:border-blue-500 focus:ring-2 focus:ring-blue-200 transition-all outline-none bg-white resize-none"
                  placeholder={t('teams:form.teamContext')}
                  rows="3"
                />
              </div>

              <div>
                <label className="text-sm font-medium text-gray-700 mb-2 flex items-center">
                  <UserCircle className="w-4 h-4 mr-2 text-blue-600" />
                  {t('teams:form.leaderLabel')}
                </label>
                <select
                  value={leaderId || ''}
                  onChange={e => setLeaderId(e.target.value ? Number(e.target.value) : null)}
                  className="w-full px-4 py-3 border border-gray-200 rounded-input focus:border-blue-500 focus:ring-2 focus:ring-blue-200 transition-all outline-none bg-white"
                >
                  <option value="">{t('teams:form.leaderPlaceholder')}</option>
                  {convAgents.map(a => (
                    <option key={a.id} value={a.id}>{a.name}</option>
                  ))}
                </select>
              </div>

              <div>
                <label className="text-sm font-medium text-gray-700 mb-2 flex items-center">
                  <Zap className="w-4 h-4 mr-2 text-purple-600" />
                  {t('teams:form.subAgentsLabel')}
                </label>
                <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
                  {actionAgentsList.map(a => (
                    <label
                      key={a.id}
                      className={`flex items-center gap-3 p-3 border rounded-button cursor-pointer transition-all ${
                        actionIds.includes(a.id)
                          ? 'bg-blue-50 border-blue-300'
                          : 'border-gray-200 hover:border-gray-300 hover:bg-gray-50'
                      }`}
                    >
                      <input
                        type="checkbox"
                        checked={actionIds.includes(a.id)}
                        onChange={() => toggleActionAgent(a.id)}
                        className="w-4 h-4 text-blue-600 rounded focus:ring-2 focus:ring-blue-500"
                      />
                      <span className="text-sm font-medium text-gray-700">{a.name}</span>
                      {actionIds.includes(a.id) && (
                        <CheckCircle2 className="w-4 h-4 ml-auto text-green-500" />
                      )}
                    </label>
                  ))}
                </div>
              </div>

              <div className="flex gap-4 pt-4 border-t border-gray-100">
                <button
                  onClick={() => router.push('/teams')}
                  className="flex-1 px-6 py-3 text-gray-700 bg-white border border-gray-200 rounded-button hover:bg-gray-50 hover:border-gray-300 transition-all font-medium"
                >
                  {t('teams:buttons.cancel')}
                </button>
                <button
                  onClick={submit}
                  disabled={creating}
                  className="flex-1 px-6 py-3 bg-gradient-to-r from-blue-600 to-purple-600 text-white rounded-button hover:from-blue-700 hover:to-purple-700 transition-all font-semibold shadow-card hover:shadow-elevated disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  {creating ? (
                    <div className="flex items-center justify-center">
                      <Loader2 className="w-5 h-5 animate-spin mr-2" />
                      {t('teams:buttons.creating')}
                    </div>
                  ) : (
                    <div className="flex items-center justify-center">
                      <Users className="w-5 h-5 mr-2" />
                      {t('teams:buttons.createTeamAction')}
                    </div>
                  )}
                </button>
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
