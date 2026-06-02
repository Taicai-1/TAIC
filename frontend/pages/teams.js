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
  CheckCircle2,
  RefreshCw,
  X,
  ChevronRight,
  ChevronLeft,
  Eye,
  Crown,
} from "lucide-react";
import Layout from '../components/Layout';
import { useAuth } from '../hooks/useAuth';
import api from '../lib/api';

export default function TeamsPage() {
  const { t } = useTranslation(['teams', 'common', 'errors']);
  const { user, loading: authLoading, authenticated, logout: authLogout } = useAuth();
  const [teams, setTeams] = useState([]);
  const [agents, setAgents] = useState([]);
  const [loading, setLoading] = useState(true);
  const [showForm, setShowForm] = useState(false);
  const [creating, setCreating] = useState(false);
  const router = useRouter();

  // Multi-step form state
  const [step, setStep] = useState(1);
  const [teamName, setTeamName] = useState("");
  const [teamContext, setTeamContext] = useState("");
  const [orchestrationPrompt, setOrchestrationPrompt] = useState("");
  const [teamMembers, setTeamMembers] = useState([]);
  const [editingTeamId, setEditingTeamId] = useState(null);

  const resetForm = () => {
    setStep(1);
    setTeamName("");
    setTeamContext("");
    setOrchestrationPrompt("");
    setTeamMembers([]);
    setEditingTeamId(null);
  };

  const openCreateForm = () => {
    resetForm();
    setShowForm(true);
  };

  const handleAddMember = async (agentId, role = 'member') => {
    const agent = agents.find(a => a.id === agentId);
    if (!agent) return;
    if (teamMembers.some(m => m.agent_id === agentId)) return;

    const newMember = {
      agent_id: agentId,
      role,
      specialization: '',
      autoSpec: '',
      name: agent.name,
      loading: true,
    };
    setTeamMembers(prev => [...prev, newMember]);

    try {
      const res = await api.post('/teams/suggest-specialization', { agent_id: agentId });
      setTeamMembers(prev => prev.map(m =>
        m.agent_id === agentId
          ? { ...m, specialization: res.data.specialization, autoSpec: res.data.specialization, loading: false }
          : m
      ));
    } catch {
      setTeamMembers(prev => prev.map(m =>
        m.agent_id === agentId ? { ...m, loading: false } : m
      ));
    }
  };

  const handleRegenerateSpec = async (agentId) => {
    setTeamMembers(prev => prev.map(m =>
      m.agent_id === agentId ? { ...m, loading: true } : m
    ));
    try {
      const res = await api.post('/teams/suggest-specialization', { agent_id: agentId });
      setTeamMembers(prev => prev.map(m =>
        m.agent_id === agentId
          ? { ...m, specialization: res.data.specialization, autoSpec: res.data.specialization, loading: false }
          : m
      ));
    } catch {
      setTeamMembers(prev => prev.map(m =>
        m.agent_id === agentId ? { ...m, loading: false } : m
      ));
      toast.error(t('teams:errors.suggestSpecialization'));
    }
  };

  const removeMember = (agentId) => {
    setTeamMembers(prev => prev.filter(m => m.agent_id !== agentId));
  };

  const updateMemberSpec = (agentId, spec) => {
    setTeamMembers(prev => prev.map(m =>
      m.agent_id === agentId ? { ...m, specialization: spec } : m
    ));
  };

  const handleSubmitTeam = async () => {
    const leaders = teamMembers.filter(m => m.role === 'leader');
    const members = teamMembers.filter(m => m.role === 'member');
    if (leaders.length !== 1) {
      toast.error(t('teams:errors.leaderRequired'));
      return;
    }
    if (members.length < 1) {
      toast.error(t('teams:errors.leaderRequired'));
      return;
    }
    setCreating(true);
    try {
      const payload = {
        name: teamName,
        contexte: teamContext || null,
        orchestration_prompt: orchestrationPrompt || null,
        members: teamMembers.map(m => ({
          agent_id: m.agent_id,
          role: m.role,
          specialization: m.specialization || null,
        })),
      };

      if (editingTeamId) {
        await api.put(`/teams/${editingTeamId}/members`, { members: payload.members });
        toast.success(t('teams:success.teamUpdated'));
      } else {
        await api.post('/teams', payload);
        toast.success(t('teams:success.teamCreated'));
      }
      setShowForm(false);
      resetForm();
      loadTeams();
    } catch (err) {
      console.error("Error saving team:", err);
      toast.error(t('teams:errors.creatingTeam'));
    } finally {
      setCreating(false);
    }
  };

  const handleEditTeam = async (teamId) => {
    try {
      const res = await api.get(`/teams/${teamId}`);
      const team = res.data.team;
      setTeamName(team.name);
      setTeamContext(team.contexte || '');
      setOrchestrationPrompt(team.orchestration_prompt || '');
      setTeamMembers((team.members || []).map(m => ({
        agent_id: m.agent_id,
        role: m.role,
        specialization: m.specialization || '',
        autoSpec: m.auto_specialization || '',
        name: m.name,
        loading: false,
      })));
      setEditingTeamId(teamId);
      setStep(1);
      setShowForm(true);
    } catch {
      toast.error(t('teams:errors.loadingTeams'));
    }
  };

  const conversationnelAgents = agents.filter(a => (a.type || 'conversationnel') === 'conversationnel');
  const availableAgents = conversationnelAgents.filter(a => !teamMembers.some(m => m.agent_id === a.id));
  const hasLeader = teamMembers.some(m => m.role === 'leader');
  const hasMembers = teamMembers.some(m => m.role === 'member');

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
            onClick={openCreateForm}
            className="group flex items-center justify-center px-8 py-4 bg-gradient-to-r from-blue-600 to-purple-600 text-white rounded-button hover:from-blue-700 hover:to-purple-700 transition-all font-semibold shadow-card hover:shadow-elevated"
          >
            <Plus className="w-6 h-6 mr-3 group-hover:rotate-90 transition-transform duration-300" />
            <span>{t('teams:buttons.createTeam')}</span>
          </button>
        </div>
        )}
        {showForm && (
          <div className="fixed inset-0 bg-black/60 backdrop-blur-sm flex items-center justify-center z-[100] p-4">
            <div className="bg-white rounded-card shadow-floating w-full max-w-2xl mx-auto max-h-[90vh] overflow-auto border border-gray-200 animate-fade-in">
              {/* Header with steps */}
              <div className="bg-gradient-to-r from-purple-600 via-blue-600 to-purple-600 p-6 rounded-t-card">
                <div className="flex items-center justify-between mb-4">
                  <h2 className="text-xl font-heading font-bold text-white flex items-center">
                    <Users className="w-6 h-6 mr-3" />
                    {editingTeamId ? t('teams:form.editTeam') : t('teams:form.title')}
                  </h2>
                  <button onClick={() => { setShowForm(false); resetForm(); }} className="text-white/80 hover:text-white">
                    <X className="w-5 h-5" />
                  </button>
                </div>
                <div className="flex items-center space-x-2">
                  {[1, 2, 3].map(s => (
                    <div key={s} className="flex items-center">
                      <div className={`w-8 h-8 rounded-full flex items-center justify-center text-sm font-bold ${
                        s <= step ? 'bg-white text-purple-600' : 'bg-white/30 text-white/70'
                      }`}>
                        {s}
                      </div>
                      <span className={`ml-2 text-sm font-medium ${s <= step ? 'text-white' : 'text-white/50'}`}>
                        {t(`teams:form.step${s}Title`)}
                      </span>
                      {s < 3 && <ChevronRight className="w-4 h-4 text-white/50 mx-2" />}
                    </div>
                  ))}
                </div>
              </div>

              <div className="p-6">
                {/* Step 1: Basic info */}
                {step === 1 && (
                  <div className="space-y-5">
                    <div>
                      <label className="text-sm font-semibold block text-gray-700 mb-2">{t('teams:form.teamName')}</label>
                      <input
                        type="text"
                        className="w-full px-4 py-3 border border-gray-200 rounded-input focus:border-primary-500 focus:ring-2 focus:ring-primary-100 transition-all outline-none bg-white"
                        placeholder={t('teams:form.teamName')}
                        value={teamName}
                        onChange={e => setTeamName(e.target.value)}
                      />
                    </div>
                    <div>
                      <label className="text-sm font-semibold block text-gray-700 mb-2">{t('teams:form.teamContext')}</label>
                      <textarea
                        className="w-full px-4 py-3 border border-gray-200 rounded-input focus:border-primary-500 focus:ring-2 focus:ring-primary-100 transition-all outline-none bg-white resize-none"
                        placeholder={t('teams:form.teamContext')}
                        value={teamContext}
                        onChange={e => setTeamContext(e.target.value)}
                        rows="3"
                      />
                    </div>
                    <div>
                      <label className="text-sm font-semibold block text-gray-700 mb-2">{t('teams:form.orchestrationPrompt')}</label>
                      <textarea
                        className="w-full px-4 py-3 border border-gray-200 rounded-input focus:border-primary-500 focus:ring-2 focus:ring-primary-100 transition-all outline-none bg-white resize-none"
                        placeholder={t('teams:form.orchestrationPrompt')}
                        value={orchestrationPrompt}
                        onChange={e => setOrchestrationPrompt(e.target.value)}
                        rows="2"
                      />
                    </div>
                  </div>
                )}

                {/* Step 2: Team composition */}
                {step === 2 && (
                  <div className="space-y-5">
                    {/* Leader selection */}
                    {!hasLeader && (
                      <div className="p-4 bg-purple-50 border border-purple-200 rounded-card">
                        <label className="text-sm font-semibold block text-purple-700 mb-2 flex items-center">
                          <Crown className="w-4 h-4 mr-2" />
                          {t('teams:form.leaderLabel')}
                        </label>
                        <select
                          className="w-full px-4 py-3 border border-purple-200 rounded-input focus:border-purple-500 focus:ring-2 focus:ring-purple-100 transition-all outline-none bg-white font-medium"
                          value=""
                          onChange={e => { if (e.target.value) handleAddMember(parseInt(e.target.value), 'leader'); }}
                        >
                          <option value="">{t('teams:form.leaderPlaceholder')}</option>
                          {availableAgents.map(agent => (
                            <option key={agent.id} value={agent.id}>{agent.name}</option>
                          ))}
                        </select>
                      </div>
                    )}

                    {/* Current members */}
                    <div className="space-y-3">
                      {teamMembers.map(m => (
                        <div key={m.agent_id} className={`p-4 rounded-card border ${m.role === 'leader' ? 'border-purple-300 bg-purple-50' : 'border-gray-200 bg-white'}`}>
                          <div className="flex items-center justify-between mb-2">
                            <div className="flex items-center">
                              {m.role === 'leader' ? <Crown className="w-4 h-4 text-purple-600 mr-2" /> : <Bot className="w-4 h-4 text-blue-600 mr-2" />}
                              <span className="font-semibold text-gray-900">{m.name}</span>
                              <span className={`ml-2 px-2 py-0.5 text-xs rounded-full font-medium ${m.role === 'leader' ? 'bg-purple-200 text-purple-700' : 'bg-blue-100 text-blue-700'}`}>
                                {m.role === 'leader' ? t('teams:form.teamLeader') : 'Member'}
                              </span>
                            </div>
                            <button onClick={() => removeMember(m.agent_id)} className="text-red-400 hover:text-red-600 transition-colors">
                              <X className="w-4 h-4" />
                            </button>
                          </div>
                          <div className="flex items-center gap-2">
                            <input
                              type="text"
                              className="flex-1 px-3 py-2 text-sm border border-gray-200 rounded-input focus:border-primary-500 focus:ring-1 focus:ring-primary-100 transition-all outline-none"
                              placeholder={t('teams:form.memberSpecialization')}
                              value={m.specialization}
                              onChange={e => updateMemberSpec(m.agent_id, e.target.value)}
                            />
                            <button
                              onClick={() => handleRegenerateSpec(m.agent_id)}
                              disabled={m.loading}
                              className="p-2 text-gray-500 hover:text-purple-600 transition-colors disabled:opacity-50"
                              title={t('teams:form.regenerateSpec')}
                            >
                              <RefreshCw className={`w-4 h-4 ${m.loading ? 'animate-spin' : ''}`} />
                            </button>
                          </div>
                          {m.autoSpec && m.specialization === m.autoSpec && (
                            <span className="text-xs text-green-600 mt-1 inline-block">{t('teams:form.autoDetected')}</span>
                          )}
                        </div>
                      ))}
                    </div>

                    {/* Add member */}
                    {hasLeader && availableAgents.length > 0 && (
                      <div className="p-4 border-2 border-dashed border-gray-300 rounded-card hover:border-blue-400 transition-colors">
                        <label className="text-sm font-semibold block text-gray-700 mb-2 flex items-center">
                          <Plus className="w-4 h-4 mr-2 text-blue-600" />
                          {t('teams:form.addMember')}
                        </label>
                        <select
                          className="w-full px-4 py-3 border border-gray-200 rounded-input focus:border-primary-500 focus:ring-2 focus:ring-primary-100 transition-all outline-none bg-white"
                          value=""
                          onChange={e => { if (e.target.value) handleAddMember(parseInt(e.target.value), 'member'); }}
                        >
                          <option value="">{t('teams:form.selectAgent')}</option>
                          {availableAgents.map(agent => (
                            <option key={agent.id} value={agent.id}>{agent.name}</option>
                          ))}
                        </select>
                      </div>
                    )}

                    {availableAgents.length === 0 && agents.length > 0 && (
                      <p className="text-sm text-gray-500 text-center py-2">{t('teams:form.noAgentsAvailable')}</p>
                    )}
                  </div>
                )}

                {/* Step 3: Preview */}
                {step === 3 && (
                  <div className="space-y-5">
                    <div className="flex items-center mb-2">
                      <Eye className="w-5 h-5 mr-2 text-purple-600" />
                      <h3 className="text-lg font-heading font-bold text-gray-900">{t('teams:form.preview')}</h3>
                    </div>

                    <div className="p-4 bg-gray-50 rounded-card border border-gray-200">
                      <p className="text-sm text-gray-500 mb-1">{t('teams:form.teamName')}</p>
                      <p className="text-lg font-bold text-gray-900">{teamName}</p>
                    </div>

                    {teamContext && (
                      <div className="p-4 bg-gray-50 rounded-card border border-gray-200">
                        <p className="text-sm text-gray-500 mb-1">{t('teams:form.teamContext')}</p>
                        <p className="text-sm text-gray-700">{teamContext}</p>
                      </div>
                    )}

                    <div className="space-y-3">
                      {teamMembers.map(m => (
                        <div key={m.agent_id} className={`flex items-center p-3 rounded-card border ${m.role === 'leader' ? 'border-purple-300 bg-purple-50' : 'border-gray-200 bg-white'}`}>
                          {m.role === 'leader' ? <Crown className="w-5 h-5 text-purple-600 mr-3 flex-shrink-0" /> : <Bot className="w-5 h-5 text-blue-600 mr-3 flex-shrink-0" />}
                          <div className="flex-1 min-w-0">
                            <p className="font-semibold text-gray-900">{m.name}</p>
                            <p className="text-xs text-gray-500 truncate">{m.specialization || '-'}</p>
                          </div>
                          <span className={`px-2 py-0.5 text-xs rounded-full font-medium ${m.role === 'leader' ? 'bg-purple-200 text-purple-700' : 'bg-blue-100 text-blue-700'}`}>
                            {m.role}
                          </span>
                        </div>
                      ))}
                    </div>
                  </div>
                )}

                {/* Navigation buttons */}
                <div className="flex justify-between mt-8 pt-4 border-t border-gray-200">
                  {step > 1 ? (
                    <button
                      onClick={() => setStep(s => s - 1)}
                      className="flex items-center px-5 py-3 text-gray-700 bg-white border border-gray-200 rounded-input hover:bg-gray-50 transition-all font-semibold"
                    >
                      <ChevronLeft className="w-4 h-4 mr-2" />
                      {t('teams:form.previousStep')}
                    </button>
                  ) : (
                    <button
                      onClick={() => { setShowForm(false); resetForm(); }}
                      className="px-5 py-3 text-gray-700 bg-white border border-gray-200 rounded-input hover:bg-gray-50 transition-all font-semibold"
                    >
                      {t('teams:buttons.cancel')}
                    </button>
                  )}

                  {step < 3 ? (
                    <button
                      onClick={() => {
                        if (step === 1 && !teamName.trim()) {
                          toast.error(t('teams:errors.nameRequired'));
                          return;
                        }
                        if (step === 2 && (!hasLeader || !hasMembers)) {
                          toast.error(t('teams:errors.leaderRequired'));
                          return;
                        }
                        setStep(s => s + 1);
                      }}
                      className="flex items-center px-5 py-3 bg-gradient-to-r from-blue-600 to-purple-600 text-white rounded-button hover:from-blue-700 hover:to-purple-700 transition-all font-semibold shadow-card"
                    >
                      {t('teams:form.nextStep')}
                      <ChevronRight className="w-4 h-4 ml-2" />
                    </button>
                  ) : (
                    <button
                      onClick={handleSubmitTeam}
                      disabled={creating}
                      className="flex items-center px-6 py-3 bg-gradient-to-r from-blue-600 to-purple-600 text-white rounded-button hover:from-blue-700 hover:to-purple-700 transition-all font-semibold shadow-card hover:shadow-elevated disabled:opacity-50"
                    >
                      {creating ? (
                        <>
                          <div className="animate-spin rounded-full h-5 w-5 border-b-2 border-white mr-2"></div>
                          {t('teams:buttons.creating')}
                        </>
                      ) : (
                        <>
                          <Users className="w-5 h-5 mr-2" />
                          {t('teams:buttons.createTeamAction')}
                        </>
                      )}
                    </button>
                  )}
                </div>
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
                          onClick={e => { e.stopPropagation(); handleEditTeam(team.id); }}
                          className="p-2.5 bg-white text-gray-600 rounded-button hover:bg-gray-50 transition-all duration-200 opacity-0 group-hover:opacity-100 shadow-subtle border border-gray-200 hover:border-gray-400"
                          title={t('teams:form.editTeam')}
                        >
                          <Pencil className="w-5 h-5" />
                        </button>
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

                    {/* Members */}
                    {(team.members || []).length > 0 && (
                      <div className="space-y-2">
                        {team.members.filter(m => m.role === 'leader').map(m => (
                          <div key={m.agent_id} className="flex items-center space-x-2 p-3 bg-gradient-to-r from-blue-50 to-purple-50 rounded-button border border-purple-200">
                            <Crown className="w-5 h-5 text-purple-600 flex-shrink-0" />
                            <div className="flex-1 min-w-0">
                              <p className="text-xs text-gray-500 font-medium">{t('teams:form.teamLeader')}</p>
                              <p className="text-sm font-bold text-gray-800 truncate">{m.name || team.leader_name || team.leader_agent_id}</p>
                            </div>
                          </div>
                        ))}
                        {team.members.filter(m => m.role === 'member').length > 0 && (
                          <div>
                            <p className="text-xs font-semibold text-gray-500 flex items-center mb-2">
                              <Zap className="w-3 h-3 mr-1" />
                              {t('teams:form.subCompanions')} ({team.members.filter(m => m.role === 'member').length})
                            </p>
                            <div className="flex flex-wrap gap-2">
                              {team.members.filter(m => m.role === 'member').map(m => (
                                <span key={m.agent_id} className="px-3 py-1 bg-gradient-to-r from-blue-100 to-purple-100 text-purple-700 rounded-full text-xs font-semibold shadow-sm border border-purple-200" title={m.specialization || ''}>
                                  {m.name}
                                </span>
                              ))}
                            </div>
                          </div>
                        )}
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
