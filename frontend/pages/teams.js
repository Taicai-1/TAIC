import { useState, useEffect } from "react";
import { useRouter } from "next/router";
import toast, { Toaster } from "react-hot-toast";
import { useTranslation } from 'next-i18next';
import { serverSideTranslations } from 'next-i18next/serverSideTranslations';
import {
  Bot,
  Plus,
  Trash2,
  Pencil,
  ArrowRight,
  Users,
  TrendingUp,
  UserCheck,
  ShoppingCart,

  UserCircle,
  Zap,
  CheckCircle2
} from "lucide-react";
import Layout from '../components/Layout';
import { useAuth } from '../hooks/useAuth';
import api from '../lib/api';

export default function TeamsPage() {
  const { t } = useTranslation(['teams', 'common', 'errors']);
  const { user, loading: authLoading, authenticated, logout: authLogout } = useAuth();
  const [editingAgent, setEditingAgent] = useState(null); // kept for modal reuse
  const [teams, setTeams] = useState([]);
  const [agents, setAgents] = useState([]);
  const [loading, setLoading] = useState(true);
  const [showForm, setShowForm] = useState(false);
  const [form, setForm] = useState({ name: "", contexte: "", leaderId: null, actionIds: [] });
  const [creating, setCreating] = useState(false);
  const router = useRouter();

  // Refactor AGENT_TYPES to use translations
  const AGENT_TYPES = {
    conversationnel: {
      key: 'conversationnel',
      name: t('teams:agentTypes.conversationnel.name'),
      icon: Users,
      color: 'bg-primary-500',
      description: t('teams:agentTypes.conversationnel.description')
    },
    actionnable: {
      key: 'actionnable',
      name: t('teams:agentTypes.actionnable.name'),
      icon: Bot,
      color: 'bg-green-500',
      description: t('teams:agentTypes.actionnable.description')
    },
    recherche_live: {
      key: 'recherche_live',
      name: t('teams:agentTypes.recherche_live.name'),
      icon: TrendingUp,
      color: 'bg-purple-500',
      description: t('teams:agentTypes.recherche_live.description')
    }
  };

  const hasNoOrg = user && !user.company_id;

  useEffect(() => {
    if (!authenticated) return;
    if (hasNoOrg) { setTeams([]); setAgents([]); setLoading(false); return; }
    loadTeams();
    loadAgents();
  }, [authenticated, hasNoOrg]);

  // Lock body scroll when modal is open
  useEffect(() => {
    const previous = document.body.style.overflow;
    if (showForm) {
      document.body.style.overflow = 'hidden';
    } else {
      document.body.style.overflow = previous || '';
    }
    return () => {
      document.body.style.overflow = previous || '';
    };
  }, [showForm]);

  const loadTeams = async () => {
    try {
      const response = await api.get('/teams');
      setTeams(response.data.teams || []);
    } catch (error) {
      console.error("Error loading teams:", error);
      if (!hasNoOrg) toast.error(t('teams:errors.loadingTeams'));
    } finally {
      setLoading(false);
    }
  };

  const loadAgents = async () => {
    try {
      const response = await api.get('/agents');
      setAgents(response.data.agents || []);
    } catch (error) {
      console.error("Error loading agents:", error);
      if (!hasNoOrg) toast.error(t('teams:errors.loadingAgents'));
    }
  };

  const deleteAgent = async (agentId) => {
    if (!confirm(t('teams:confirmations.deleteAgent'))) {
      return;
    }
    try {
      await api.delete(`/agents/${agentId}`);
      toast.success(t('teams:success.agentDeleted'));
      loadAgents();
    } catch (error) {
      console.error("Error deleting agent:", error);
      toast.error(t('teams:errors.deletingAgent'));
    }
  };

  if (loading || authLoading) {
    return (
      <div className="min-h-screen bg-gray-50 flex items-center justify-center">
        <div className="flex flex-col items-center">
          <div className="animate-spin rounded-full h-16 w-16 border-b-4 border-primary-600 mb-4"></div>
          <p className="text-gray-600 font-medium">{t('teams:page.loading')}</p>
        </div>
      </div>
    );
  }

  return (
    <Layout title={t('teams:page.title')} onLogout={authLogout}>
      <Toaster position="top-right" />

      {/* Create New Team Button */}
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        {!hasNoOrg && (
        <div className="flex justify-end">
          <button
            onClick={() => { setForm({ name: "", contexte: "", leaderId: null, actionIds: [] }); setShowForm(true); }}
            className="group flex items-center justify-center px-8 py-4 bg-gradient-to-r from-blue-600 to-purple-600 text-white rounded-button hover:from-blue-700 hover:to-purple-700 transition-all font-semibold shadow-card hover:shadow-elevated"
          >
            <Plus className="w-6 h-6 mr-3 group-hover:rotate-90 transition-transform duration-300" />
            <span>{t('teams:buttons.createTeam')}</span>
          </button>
        </div>
        )}
        {showForm && (
          <div className="fixed inset-0 bg-black/60 backdrop-blur-sm flex items-center justify-center z-[100] p-4">
            <div className="bg-white rounded-card shadow-floating p-8 w-full max-w-md mx-auto max-h-[85vh] overflow-auto border border-gray-200 animate-fade-in">
              <div className="flex items-center mb-6">
                <Users className="w-6 h-6 mr-3 text-purple-600" />
                <h2 className="text-2xl font-heading font-bold text-gray-900">
                  {t('teams:form.title')}
                </h2>
              </div>
              <div className="space-y-4">
                <input
                  type="text"
                  className="w-full px-4 py-3 border border-gray-200 rounded-input focus:border-primary-500 focus:ring-2 focus:ring-primary-100 transition-all outline-none bg-white"
                  placeholder={t('teams:form.teamName')}
                  value={form.name}
                  onChange={e => setForm(f => ({...f, name: e.target.value}))}
                />
                <textarea
                  className="w-full px-4 py-3 border border-gray-200 rounded-input focus:border-primary-500 focus:ring-2 focus:ring-primary-100 transition-all outline-none bg-white resize-none"
                  placeholder={t('teams:form.teamContext')}
                  value={form.contexte}
                  onChange={e => setForm(f => ({...f, contexte: e.target.value}))}
                  rows="3"
                />

                <div>
                  <label className="text-sm font-semibold mb-3 block text-gray-700 flex items-center">
                    <UserCircle className="w-4 h-4 mr-2 text-primary-600" />
                    {t('teams:form.leaderLabel')}
                  </label>
                  <select
                    className="w-full px-4 py-3 border border-gray-200 rounded-input focus:border-primary-500 focus:ring-2 focus:ring-primary-100 transition-all outline-none bg-white font-medium"
                    value={form.leaderId || ""}
                    onChange={e => setForm(f => ({...f, leaderId: e.target.value ? parseInt(e.target.value) : null}))}
                  >
                    <option value="">{t('teams:form.leaderPlaceholder')}</option>
                    {agents.filter(a => a.type === 'conversationnel').map(agent => (
                      <option key={agent.id} value={agent.id}>{agent.name}</option>
                    ))}
                  </select>
                </div>

                <div>
                  <label className="text-sm font-semibold mb-3 block text-gray-700 flex items-center">
                    <Zap className="w-4 h-4 mr-2 text-purple-600" />
                    {t('teams:form.subAgentsLabel')}
                  </label>
                  <div className="space-y-2 max-h-40 overflow-y-auto p-3 bg-white/50 rounded-button border-2 border-gray-200">
                    {agents.filter(a => (a.type || 'conversationnel') === 'conversationnel').map(agent => (
                      <label key={agent.id} className="flex items-center p-2 hover:bg-primary-50 rounded-sm transition-colors cursor-pointer group">
                        <input
                          type="checkbox"
                          checked={form.actionIds.includes(agent.id)}
                          onChange={e => {
                            const id = agent.id;
                            setForm(f => ({
                              ...f,
                              actionIds: e.target.checked
                                ? [...f.actionIds, id]
                                : f.actionIds.filter(x => x !== id)
                            }));
                          }}
                          className="mr-3 w-5 h-5 text-primary-600 rounded focus:ring-2 focus:ring-primary-500"
                        />
                        <span className="text-sm font-medium text-gray-700 group-hover:text-primary-700 transition-colors">{agent.name}</span>
                        {form.actionIds.includes(agent.id) && (
                          <CheckCircle2 className="w-4 h-4 ml-auto text-green-500" />
                        )}
                      </label>
                    ))}
                  </div>
                </div>
              </div>
            <div className="flex space-x-4 mt-8">
              <button
                onClick={() => setShowForm(false)}
                className="flex-1 px-6 py-3 text-gray-700 bg-white border border-gray-200 rounded-input hover:bg-gray-50 hover:border-gray-300 transition-all duration-300 font-semibold shadow-card"
              >
                {t('teams:buttons.cancel')}
              </button>
              <button
                onClick={async () => {
                  if (!form.name.trim()) {
                    toast.error(t('teams:errors.nameRequired'));
                    return;
                  }
                  if (!form.leaderId) {
                    toast.error(t('teams:errors.leaderRequired'));
                    return;
                  }
                  setCreating(true);
                  try {
                    const payload = {
                      name: form.name,
                      contexte: form.contexte,
                      leader_agent_id: form.leaderId,
                      action_agent_ids: form.actionIds
                    };
                    await api.post('/teams', payload);
                    toast.success(t('teams:success.teamCreated'));
                    setShowForm(false);
                    setForm({ name: "", contexte: "", leaderId: null, actionIds: [] });
                    loadTeams();
                  } catch (err) {
                    console.error("Error creating team:", err);
                    toast.error(t('teams:errors.creatingTeam'));
                  } finally {
                    setCreating(false);
                  }
                }}
                className="flex-1 px-6 py-3 bg-gradient-to-r from-blue-600 to-purple-600 text-white rounded-button hover:from-blue-700 hover:to-purple-700 transition-all font-semibold shadow-card hover:shadow-elevated disabled:opacity-50 disabled:cursor-not-allowed"
                disabled={creating}
              >
                {creating ? (
                  <div className="flex items-center justify-center">
                    <div className="animate-spin rounded-full h-5 w-5 border-b-2 border-white mr-2"></div>
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
        )}
      </div>

      {/* Teams Grid - Hidden when form is shown */}
      {!showForm && (
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 pb-12">
        {teams.length === 0 ? (
          <div className="text-center py-20">
            <div className="relative inline-block">
              <Users className="w-24 h-24 mx-auto text-gray-300 mb-6" />
              {!hasNoOrg && (
                <div className="absolute -top-2 -right-2 w-8 h-8 bg-purple-500 rounded-full flex items-center justify-center animate-bounce">
                  <Plus className="w-5 h-5 text-white" />
                </div>
              )}
            </div>
            {hasNoOrg ? (
              <>
                <h3 className="text-2xl font-bold text-gray-700 mb-2">{t('teams:emptyState.noOrgTitle')}</h3>
                <p className="text-gray-500">{t('teams:emptyState.noOrgDescription')}</p>
              </>
            ) : (
              <>
                <h3 className="text-2xl font-bold text-gray-700 mb-2">{t('teams:emptyState.title')}</h3>
                <p className="text-gray-500">{t('teams:emptyState.description')}</p>
              </>
            )}
          </div>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-8">
            {teams.map((team) => {
              return (
                <div
                  key={team.id}
                  className="group bg-white rounded-card shadow-card border border-gray-200 hover:border-gray-300 hover:shadow-elevated transition-all duration-200 cursor-pointer overflow-hidden animate-fade-in"
                  onClick={() => router.push(`/chat/team/${team.id}`)}
                >
                  {/* Gradient header */}
                  <div className="h-20 bg-gradient-to-r from-purple-500 via-blue-500 to-purple-500">
                  </div>

                  <div className="p-6 -mt-12">
                    <div className="flex items-start justify-between mb-4">
                      <div className="relative z-10 p-4 rounded-card bg-gradient-to-br from-purple-100 to-blue-100 shadow-card ring-4 ring-white">
                        <Users className="w-10 h-10 text-purple-600" />
                      </div>
                      <div className="flex space-x-2 pt-12">
                        <button
                          onClick={e => { e.stopPropagation(); router.push(`/chat/team/${team.id}`); }}
                          className="p-2.5 bg-white text-purple-600 rounded-button hover:bg-purple-50 transition-all duration-200 opacity-0 group-hover:opacity-100 shadow-subtle border border-purple-200 hover:border-purple-400"
                          title={t('teams:buttons.open')}
                        >
                          <ArrowRight className="w-5 h-5" />
                        </button>
                      </div>
                    </div>

                    <h3 className="text-2xl font-heading font-bold text-gray-900 mb-3 group-hover:text-purple-600 transition-colors">{team.name}</h3>

                    {/* Leader badge */}
                    <div className="flex items-center space-x-2 mb-4 p-3 bg-gradient-to-r from-blue-50 to-purple-50 rounded-button border border-purple-200">
                      <UserCircle className="w-5 h-5 text-purple-600 flex-shrink-0" />
                      <div>
                        <p className="text-xs text-gray-500 font-medium">{t('teams:form.teamLeader')}</p>
                        <p className="text-sm font-bold text-gray-800">{team.leader_name || team.leader_agent_id}</p>
                      </div>
                    </div>

                    {/* Sub-agents */}
                    {(team.action_agent_names || []).length > 0 && (
                      <div className="space-y-2">
                        <p className="text-xs font-semibold text-gray-500 flex items-center">
                          <Zap className="w-3 h-3 mr-1" />
                          {t('teams:form.subCompanions')} ({team.action_agent_names.length})
                        </p>
                        <div className="flex flex-wrap gap-2">
                          {(team.action_agent_names || []).map((n, i) => (
                            <span key={i} className="px-3 py-1 bg-gradient-to-r from-blue-100 to-purple-100 text-purple-700 rounded-full text-xs font-semibold shadow-sm border border-purple-200">
                              {n}
                            </span>
                          ))}
                        </div>
                      </div>
                    )}
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </div>
      )}
    </Layout>
  );
}

export async function getServerSideProps({ locale }) {
  // Auth check is handled client-side via useAuth hook
  return {
    props: {
      ...(await serverSideTranslations(locale, ['teams', 'common', 'errors'])),
    },
  };
}
