import { useState, useEffect, useCallback } from "react";
import { useRouter } from "next/router";
import toast, { Toaster } from "react-hot-toast";
import { useTranslation } from 'next-i18next';
import { serverSideTranslations } from 'next-i18next/serverSideTranslations';
import { useAuth } from '../hooks/useAuth';
import api from '../lib/api';
import {
  Bot,
  Plus,
  ArrowRight,
  Users,
  MessageCircle,
  Zap,
  FileText,
  Database,
  MessageSquarePlus,
  Send,
  X,
  Image as ImageIcon,
  Search
} from "lucide-react";
import Layout from '../components/Layout';
import AgentCard from '../components/AgentCard';

export default function AgentsPage() {
  const { t } = useTranslation(['agents', 'common', 'errors']);
  const { user, loading: authLoading, authenticated, logout: authLogout } = useAuth();
  const [agents, setAgents] = useState([]);
  const [loading, setLoading] = useState(true);
  const [showForm, setShowForm] = useState(false);
  const [form, setForm] = useState({ name: "", contexte: "", biographie: "", profile_photo: null, email: "", password: "", type: 'conversationnel', email_tags: [], neo4j_enabled: false, neo4j_person_name: "", neo4j_depth: 1, weekly_recap_enabled: false, weekly_recap_prompt: "", weekly_recap_recipients: [] });
  const [emailTagInput, setEmailTagInput] = useState("");
  const [photoPreview, setPhotoPreview] = useState(null);
  const [photoPreviewError, setPhotoPreviewError] = useState(false);
  const [creating, setCreating] = useState(false);
  const [neo4jPersons, setNeo4jPersons] = useState([]);
  const [userCompany, setUserCompany] = useState(null);
  const [showFeedback, setShowFeedback] = useState(false);
  const [feedbackType, setFeedbackType] = useState("bug");
  const [feedbackMessage, setFeedbackMessage] = useState("");
  const [sendingFeedback, setSendingFeedback] = useState(false);
  const [search, setSearch] = useState('');
  const router = useRouter();

  useEffect(() => {
    if (!authenticated) return;
    loadAgents();
    loadNeo4jData();
  }, [authenticated]);

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

  const hasNoOrg = user && !user.company_id;

  const loadAgents = useCallback(async () => {
    if (hasNoOrg) { setAgents([]); setLoading(false); return; }
    try {
      const response = await api.get('/agents');
      setAgents(response.data.agents || []);
    } catch (error) {
      if (!hasNoOrg) toast.error(t('agents:toast.loadError'));
      if (error.response?.status === 401) {
        router.push("/login");
      }
    } finally {
      setLoading(false);
    }
  }, [t, router, hasNoOrg]);

  const loadNeo4jData = async () => {
    try {
      const [companyRes, personsRes] = await Promise.all([
        api.get('/api/companies/mine'),
        api.get('/api/neo4j/persons')
      ]);
      setUserCompany(companyRes.data.company);
      setNeo4jPersons(personsRes.data.persons || []);
    } catch (error) {
      // Neo4j data is optional, silent fail
    }
  };

  const deleteAgent = useCallback(async (agentId) => {
    if (!confirm(t('agents:toast.deleteConfirm'))) {
      return;
    }
    try {
      await api.delete(`/agents/${agentId}`);
      toast.success(t('agents:toast.deleted'));
      loadAgents();
    } catch (error) {
      toast.error(t('agents:toast.deleteError'));
      if (error.response?.status === 401) {
        router.push("/login");
      }
    }
  }, [t, router, loadAgents]);

  const logout = () => {
    authLogout();
  };

  const handleSendFeedback = async () => {
    if (!feedbackMessage.trim()) return;
    setSendingFeedback(true);
    try {
      await api.post('/feedback', {
        type: feedbackType,
        message: feedbackMessage
      });
      toast.success(t('agents:feedback.success'));
      setShowFeedback(false);
      setFeedbackMessage("");
      setFeedbackType("bug");
    } catch (err) {
      toast.error(err.response?.data?.detail || t('agents:feedback.error'));
    } finally {
      setSendingFeedback(false);
    }
  };

  if (authLoading || loading) {
    return (
      <div className="min-h-screen bg-gray-50">
        <div className="bg-white border-b border-gray-200">
          <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
            <div className="flex justify-between items-center h-16">
              <div className="flex items-center space-x-3">
                <div className="h-6 w-48 bg-gray-200 rounded-sm animate-pulse"></div>
              </div>
              <div className="flex items-center space-x-2">
                <div className="w-10 h-10 bg-gray-100 rounded-button animate-pulse"></div>
                <div className="w-10 h-10 bg-gray-100 rounded-button animate-pulse"></div>
              </div>
            </div>
          </div>
        </div>
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
            {[1, 2, 3].map((i) => (
              <div key={i} className="bg-white rounded-card shadow-card border border-gray-100 overflow-hidden">
                <div className="h-20 bg-gradient-to-r from-gray-200 to-gray-300 animate-pulse"></div>
                <div className="p-6 -mt-10">
                  <div className="w-16 h-16 bg-gray-200 rounded-full border-4 border-white shadow-card animate-pulse mb-4"></div>
                  <div className="h-5 w-3/4 bg-gray-200 rounded-sm animate-pulse mb-3"></div>
                  <div className="flex space-x-2 mb-4">
                    <div className="h-6 w-20 bg-gray-200 rounded-full animate-pulse"></div>
                  </div>
                  <div className="h-11 w-full bg-gray-200 rounded-button animate-pulse"></div>
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>
    );
  }

  const filtered = agents.filter(a => a.name.toLowerCase().includes(search.toLowerCase()));

  return (
    <Layout title={t('agents:pageTitle')} onFeedback={() => setShowFeedback(true)} onLogout={logout}>
      <Toaster position="top-right" />

      {/* Create New Agent Button + Switch to Teams */}
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        {!hasNoOrg && (
        <div className="flex flex-col md:flex-row items-stretch md:items-center justify-between gap-4">
          <button
            onClick={() => {
              setForm({ name: "", contexte: "", biographie: "", profile_photo: null, email: "", password: "", type: 'conversationnel', email_tags: [], neo4j_enabled: false, neo4j_person_name: "", neo4j_depth: 1, weekly_recap_enabled: false, weekly_recap_prompt: "", weekly_recap_recipients: [] });
              setPhotoPreview(null);
              setShowForm(true);
            }}
            className="group flex items-center justify-center px-8 py-3.5 bg-primary-600 hover:bg-primary-700 text-white rounded-button transition-all font-semibold shadow-card hover:shadow-elevated"
          >
            <Plus className="w-5 h-5 mr-2 group-hover:rotate-90 transition-transform duration-300" />
            <span>{t('agents:buttons.createNew')}</span>
          </button>
          <button
            onClick={() => router.push('/teams')}
            className="group flex items-center justify-center px-8 py-3.5 bg-white text-gray-700 border border-gray-200 rounded-button hover:bg-gray-50 hover:border-gray-300 transition-all font-medium shadow-subtle hover:shadow-card"
            title={t('agents:buttons.teamCompanionsTooltip')}
          >
            <Users className="w-5 h-5 mr-2" />
            <span>{t('agents:buttons.teamCompanions')}</span>
            <ArrowRight className="w-5 h-5 ml-2 group-hover:translate-x-1 transition-transform" />
          </button>
        </div>
        )}
        {showForm && (
          <div className="fixed inset-0 bg-black/50 backdrop-blur-sm flex items-center justify-center z-[100] p-4">
            <div className="bg-white rounded-card shadow-floating p-8 w-full max-w-md mx-auto max-h-[85vh] overflow-auto border border-gray-200 animate-fade-in">
              <div className="flex items-center justify-between mb-6">
                <h2 className="text-xl font-heading font-bold text-gray-900">
                  {t('agents:modal.titleCreate')}
                </h2>
              </div>
              <div className="space-y-4">
              <input
                type="text"
                className="w-full px-4 py-3 border border-gray-200 rounded-input focus:border-primary-500 focus:ring-2 focus:ring-primary-100 transition-all outline-none bg-white"
                placeholder={t('agents:form.name.placeholder')}
                value={form.name}
                onChange={e => setForm(f => ({...f, name: e.target.value}))}
              />
              <textarea
                className="w-full px-4 py-3 border border-gray-200 rounded-input focus:border-primary-500 focus:ring-2 focus:ring-primary-100 transition-all outline-none bg-white resize-none"
                placeholder={t('agents:form.context.placeholder')}
                rows="3"
                value={form.contexte}
                onChange={e => setForm(f => ({...f, contexte: e.target.value}))}
              />
              <textarea
                className="w-full px-4 py-3 border border-gray-200 rounded-input focus:border-primary-500 focus:ring-2 focus:ring-primary-100 transition-all outline-none bg-white resize-none"
                placeholder={t('agents:form.biography.placeholder')}
                rows="3"
                value={form.biographie}
                onChange={e => setForm(f => ({...f, biographie: e.target.value}))}
              />
              <div>
                <label className="text-sm font-medium mb-2 block text-gray-700 flex items-center" htmlFor="model-choice-select">
                  <Zap className="w-4 h-4 mr-2 text-purple-600" />
                  {t('agents:form.modelChoice.label')}
                </label>
                <select
                  id="model-choice-select"
                  className="w-full px-4 py-3 border border-gray-200 rounded-input focus:border-primary-500 focus:ring-2 focus:ring-primary-100 transition-all outline-none bg-white font-medium"
                  value={form.type}
                  onChange={e => {
                    setForm(f => ({ ...f, type: e.target.value }));
                  }}
                >
                  <option value="conversationnel">{t('agents:types.conversationnel.name')} - {t('agents:types.conversationnel.description')}</option>
                  <option value="recherche_live">{t('agents:types.recherche_live.name')} - {t('agents:types.recherche_live.description')}</option>
                  <option value="visuel">{t('agents:types.visuel.name')} - {t('agents:types.visuel.description')}</option>
                </select>
              </div>
              <div>
                <label className="text-sm font-medium mb-2 block text-gray-700 flex items-center">
                  <MessageCircle className="w-4 h-4 mr-2 text-purple-600" />
                  {t('agents:form.emailTags.label')}
                </label>
                <div className="flex flex-wrap gap-2 mb-2">
                  {(form.email_tags || []).map((tag, index) => (
                    <span
                      key={index}
                      className="inline-flex items-center px-3 py-1 bg-purple-100 text-purple-700 rounded-full text-sm font-medium"
                    >
                      {tag}
                      <button
                        type="button"
                        onClick={() => {
                          setForm(f => ({
                            ...f,
                            email_tags: f.email_tags.filter((_, i) => i !== index)
                          }));
                        }}
                        className="ml-2 text-purple-500 hover:text-purple-700"
                      >
                        ×
                      </button>
                    </span>
                  ))}
                </div>
                <div className="flex gap-2">
                  <input
                    type="text"
                    className="flex-1 px-4 py-2 border border-gray-200 rounded-input focus:border-purple-500 focus:ring-2 focus:ring-purple-200 transition-all outline-none bg-white text-sm"
                    placeholder={t('agents:form.emailTags.placeholder')}
                    value={emailTagInput}
                    onChange={e => setEmailTagInput(e.target.value)}
                    onKeyDown={e => {
                      if (e.key === 'Enter' && emailTagInput.trim()) {
                        e.preventDefault();
                        const newTag = `@${emailTagInput.trim().toLowerCase().replace(/^@/, '')}`;
                        if (!form.email_tags.includes(newTag)) {
                          setForm(f => ({
                            ...f,
                            email_tags: [...(f.email_tags || []), newTag]
                          }));
                        }
                        setEmailTagInput("");
                      }
                    }}
                  />
                  <button
                    type="button"
                    onClick={() => {
                      if (emailTagInput.trim()) {
                        const newTag = `@${emailTagInput.trim().toLowerCase().replace(/^@/, '')}`;
                        if (!form.email_tags.includes(newTag)) {
                          setForm(f => ({
                            ...f,
                            email_tags: [...(f.email_tags || []), newTag]
                          }));
                        }
                        setEmailTagInput("");
                      }
                    }}
                    className="px-4 py-2 bg-purple-600 text-white rounded-button hover:bg-purple-700 transition-colors text-sm font-medium"
                  >
                    {t('agents:buttons.addTag')}
                  </button>
                </div>
                <p className="text-xs text-gray-500 mt-1">
                  {t('agents:form.emailTags.helpText')}
                </p>
              </div>
              {/* Neo4j Knowledge Graph Section */}
              {userCompany && userCompany.neo4j_enabled && (
                <div className="p-4 bg-gradient-to-br from-teal-50 to-cyan-50 rounded-button border border-teal-200">
                  <div className="flex items-center justify-between mb-3">
                    <label className="text-sm font-medium text-gray-700 flex items-center">
                      <Database className="w-4 h-4 mr-2 text-teal-600" />
                      {t('agents:form.neo4j.label')}
                    </label>
                    <button
                      type="button"
                      className={`w-14 h-7 flex items-center rounded-full px-1 transition-colors duration-200 focus:outline-none border border-teal-600 ${form.neo4j_enabled ? 'bg-teal-600' : 'bg-gray-200'}`}
                      onClick={() => setForm(f => ({ ...f, neo4j_enabled: !f.neo4j_enabled }))}
                    >
                      <span
                        className={`h-5 w-5 rounded-full shadow transition-transform duration-200 ${form.neo4j_enabled ? 'bg-white translate-x-7' : 'bg-gray-400 translate-x-0'}`}
                      />
                    </button>
                  </div>
                  {form.neo4j_enabled && (
                    <div className="space-y-3 mt-3">
                      <div>
                        <label className="text-xs font-medium text-gray-600 mb-1 block">{t('agents:form.neo4j.person')}</label>
                        <select
                          className="w-full px-3 py-2 border border-teal-200 rounded-sm focus:border-teal-500 focus:ring-2 focus:ring-teal-200 transition-all outline-none bg-white text-sm"
                          value={form.neo4j_person_name}
                          onChange={e => setForm(f => ({ ...f, neo4j_person_name: e.target.value }))}
                        >
                          <option value="">{t('agents:form.neo4j.selectPerson')}</option>
                          {neo4jPersons.map(p => (
                            <option key={p.name} value={p.name}>{p.name} ({p.role})</option>
                          ))}
                        </select>
                      </div>
                      <div>
                        <label className="text-xs font-medium text-gray-600 mb-1 block">{t('agents:form.neo4j.depth')}</label>
                        <select
                          className="w-full px-3 py-2 border border-teal-200 rounded-sm focus:border-teal-500 focus:ring-2 focus:ring-teal-200 transition-all outline-none bg-white text-sm"
                          value={form.neo4j_depth}
                          onChange={e => setForm(f => ({ ...f, neo4j_depth: parseInt(e.target.value) }))}
                        >
                          <option value={1}>{t('agents:form.neo4j.depth1')}</option>
                          <option value={2}>{t('agents:form.neo4j.depth2')}</option>
                        </select>
                      </div>
                    </div>
                  )}
                </div>
              )}
              {/* Weekly Recap Section */}
              <div className="p-4 bg-gradient-to-br from-amber-50 to-orange-50 rounded-button border border-amber-200">
                <div className="flex items-center justify-between mb-1">
                  <label className="text-sm font-medium text-gray-700 flex items-center">
                    <FileText className="w-4 h-4 mr-2 text-amber-600" />
                    {t('agents:form.weeklyRecap.label')}
                  </label>
                  <button
                    type="button"
                    className={`w-14 h-7 flex items-center rounded-full px-1 transition-colors duration-200 focus:outline-none border border-amber-500 ${form.weekly_recap_enabled ? 'bg-amber-500' : 'bg-gray-200'}`}
                    onClick={() => setForm(f => ({ ...f, weekly_recap_enabled: !f.weekly_recap_enabled }))}
                  >
                    <span
                      className={`h-5 w-5 rounded-full shadow transition-transform duration-200 ${form.weekly_recap_enabled ? 'bg-white translate-x-7' : 'bg-gray-400 translate-x-0'}`}
                    />
                  </button>
                </div>
                <p className="text-xs text-gray-500">{t('agents:form.weeklyRecap.helpText')}</p>
              </div>

              <div className="flex flex-col items-center space-y-4 p-6 bg-gray-50 rounded-card border border-dashed border-gray-300">
                {photoPreview && !photoPreviewError ? (
                  <div className="relative group">
                    <img
                      src={photoPreview}
                      alt=""
                      className="w-28 h-28 object-cover rounded-full border-4 border-primary-500 shadow-card ring-4 ring-primary-100"
                      onError={() => setPhotoPreviewError(true)}
                    />
                    <div className="absolute inset-0 bg-primary-600/20 rounded-full opacity-0 group-hover:opacity-100 transition-opacity"></div>
                  </div>
                ) : (
                  <div className="w-28 h-28 rounded-full border-4 border-dashed border-gray-300 flex items-center justify-center text-gray-400 bg-white shadow-subtle">
                    {form.profile_photo ? <ImageIcon className="w-12 h-12 text-primary-500" /> : <Plus className="w-12 h-12" />}
                  </div>
                )}
                <label className="group px-6 py-3 bg-primary-600 hover:bg-primary-700 text-white rounded-button font-semibold cursor-pointer transition-all shadow-card hover:shadow-elevated flex items-center">
                  {form.profile_photo ? t('agents:buttons.changePhoto') : t('agents:buttons.choosePhoto')}
                  <input
                    type="file"
                    accept="image/*"
                    className="hidden"
                    onChange={e => {
                      if (e.target.files && e.target.files[0]) {
                        const file = e.target.files[0];
                        setForm(f => ({...f, profile_photo: file}));
                        setPhotoPreviewError(false);
                        setPhotoPreview(URL.createObjectURL(file));
                      }
                    }}
                  />
                </label>
              </div>

            </div>
            <div className="flex space-x-4 mt-8">
              <button
                onClick={() => {
                  setShowForm(false);
                  setPhotoPreview(null);
                }}
                className="flex-1 px-6 py-3 text-gray-700 bg-white border border-gray-200 rounded-button hover:bg-gray-50 hover:border-gray-300 transition-all font-medium"
              >
                {t('agents:buttons.cancel')}
              </button>
              <button
                onClick={async () => {
                  if (!form.name.trim()) {
                    toast.error(t('agents:toast.nameRequired'));
                    return;
                  }
                  setCreating(true);
                  try {
                    const formData = new FormData();
                    formData.append("name", form.name);
                    formData.append("contexte", form.contexte);
                    formData.append("biographie", form.biographie);
                    if (form.profile_photo) formData.append("profile_photo", form.profile_photo);
                    formData.append("type", form.type || 'conversationnel');
                    if (form.email_tags && form.email_tags.length > 0) {
                      formData.append("email_tags", JSON.stringify(form.email_tags));
                    } else {
                      formData.append("email_tags", "[]");
                    }
                    formData.append("neo4j_enabled", form.neo4j_enabled ? "true" : "false");
                    if (form.neo4j_person_name) formData.append("neo4j_person_name", form.neo4j_person_name);
                    formData.append("neo4j_depth", String(form.neo4j_depth || 1));
                    formData.append("weekly_recap_enabled", form.weekly_recap_enabled ? "true" : "false");
                    if (form.weekly_recap_prompt) formData.append("weekly_recap_prompt", form.weekly_recap_prompt);
                    if (form.weekly_recap_recipients && form.weekly_recap_recipients.length > 0) {
                      formData.append("weekly_recap_recipients", JSON.stringify(form.weekly_recap_recipients));
                    }
                    await api.post('/agents', formData, {
                      headers: {
                        "Content-Type": "multipart/form-data"
                      }
                    });
                    toast.success(t('agents:toast.createSuccess'));
                    setShowForm(false);
                    setPhotoPreview(null);
                    setForm({ name: "", contexte: "", biographie: "", profile_photo: null, email: "", password: "", type: 'conversationnel', email_tags: [], neo4j_enabled: false, neo4j_person_name: "", neo4j_depth: 1, weekly_recap_enabled: false, weekly_recap_prompt: "", weekly_recap_recipients: [] });
                    loadAgents();
                  } catch (err) {
                    toast.error(t('agents:toast.createError'));
                  } finally {
                    setCreating(false);
                  }
                }}
                className="flex-1 px-6 py-3 bg-primary-600 hover:bg-primary-700 text-white rounded-button transition-all font-semibold shadow-card hover:shadow-elevated disabled:opacity-50 disabled:cursor-not-allowed"
                disabled={creating}
              >
                {creating ? (
                  <div className="flex items-center justify-center">
                    <div className="animate-spin rounded-full h-5 w-5 border-b-2 border-white mr-2"></div>
                    {t('agents:buttons.creating')}
                  </div>
                ) : (
                  <div className="flex items-center justify-center">
                    <Plus className="w-5 h-5 mr-2" />
                    {t('agents:buttons.create')}
                  </div>
                )}
              </button>
            </div>
            </div>
          </div>
        )}
      </div>

      {/* Agents Grid */}
      {!showForm && (
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 pb-12">
        {agents.length === 0 ? (
          <div className="text-center py-20">
            <div className="relative inline-block">
              <Bot className="w-24 h-24 mx-auto text-gray-300 mb-6" />
              {!hasNoOrg && (
                <div className="absolute -top-2 -right-2 w-8 h-8 bg-primary-500 rounded-full flex items-center justify-center animate-bounce">
                  <Plus className="w-5 h-5 text-white" />
                </div>
              )}
            </div>
            {hasNoOrg ? (
              <>
                <h3 className="text-2xl font-heading font-bold text-gray-700 mb-2">{t('agents:empty.noOrgTitle')}</h3>
                <p className="text-gray-500">{t('agents:empty.noOrgSubtitle')}</p>
              </>
            ) : (
              <>
                <h3 className="text-2xl font-heading font-bold text-gray-700 mb-2">{t('agents:empty.title')}</h3>
                <p className="text-gray-500">{t('agents:empty.subtitle')}</p>
              </>
            )}
          </div>
        ) : (
          <>
            <div className="flex items-center gap-3 mb-6">
              <div className="flex items-center gap-2 px-3 py-2 bg-white border border-gray-200 rounded-input w-64">
                <Search className="w-4 h-4 text-gray-400" />
                <input value={search} onChange={e => setSearch(e.target.value)}
                  placeholder="Rechercher un agent…"
                  className="flex-1 text-sm bg-transparent outline-none" />
              </div>
            </div>
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
              {filtered.map((agent) => (
                <AgentCard
                  key={agent.id}
                  agent={agent}
                  onChat={() => router.push(`/chat/${agent.id}`)}
                  onEdit={() => router.push(`/?agentId=${agent.id}`)}
                  onDelete={() => deleteAgent(agent.id)}
                />
              ))}
            </div>
          </>
        )}
      </div>
      )}

      {/* Feedback Modal */}
      {showFeedback && (
        <div className="fixed inset-0 bg-black/50 backdrop-blur-sm flex items-center justify-center p-4 z-50 animate-fade-in">
          <div className="bg-white rounded-card shadow-floating max-w-lg w-full animate-scale-in">
            <div className="px-6 py-5 border-b border-gray-100 rounded-t-card flex items-center justify-between">
              <div className="flex items-center space-x-3">
                <div className="w-10 h-10 rounded-button flex items-center justify-center bg-gradient-to-br from-blue-500 to-purple-500">
                  <MessageSquarePlus className="w-5 h-5 text-white" />
                </div>
                <div>
                  <h3 className="text-lg font-heading font-bold text-gray-900">{t('agents:feedback.title')}</h3>
                  <p className="text-sm text-gray-500">{t('agents:feedback.subtitle')}</p>
                </div>
              </div>
              <button onClick={() => setShowFeedback(false)} className="text-gray-400 hover:text-gray-600 transition-colors">
                <X className="w-5 h-5" />
              </button>
            </div>

            <div className="px-6 py-6 space-y-4">
              <div className="flex flex-wrap gap-2">
                {["bug", "feature", "feedback", "other"].map((type) => (
                  <button
                    key={type}
                    onClick={() => setFeedbackType(type)}
                    className={`px-4 py-2 rounded-button text-sm font-medium transition-all ${
                      feedbackType === type
                        ? "bg-gradient-to-r from-blue-600 to-purple-600 text-white shadow-card"
                        : "bg-gray-100 text-gray-600 hover:bg-gray-200"
                    }`}
                  >
                    {t(`agents:feedback.type${type.charAt(0).toUpperCase() + type.slice(1)}`)}
                  </button>
                ))}
              </div>

              <textarea
                value={feedbackMessage}
                onChange={(e) => setFeedbackMessage(e.target.value)}
                placeholder={t('agents:feedback.messagePlaceholder')}
                rows={5}
                maxLength={5000}
                className="w-full px-4 py-3 border border-gray-200 rounded-input placeholder-gray-400 focus:outline-none focus:ring-2 focus:ring-purple-500 focus:border-purple-500 transition-all bg-white resize-none"
              />

              <div className="flex space-x-3">
                <button
                  onClick={() => setShowFeedback(false)}
                  className="flex-1 py-3 px-4 text-gray-600 bg-gray-100 hover:bg-gray-200 font-medium rounded-button transition-all"
                >
                  {t('agents:feedback.cancel')}
                </button>
                <button
                  onClick={handleSendFeedback}
                  disabled={sendingFeedback || !feedbackMessage.trim()}
                  className="flex-1 py-3 px-4 bg-primary-600 hover:bg-primary-700 text-white font-semibold rounded-button shadow-card disabled:opacity-50 disabled:cursor-not-allowed transition-all flex items-center justify-center"
                >
                  {sendingFeedback ? (
                    <>
                      <div className="animate-spin rounded-full h-5 w-5 border-b-2 border-white mr-2"></div>
                      {t('agents:feedback.sending')}
                    </>
                  ) : (
                    <>
                      <Send className="w-5 h-5 mr-2" />
                      {t('agents:feedback.send')}
                    </>
                  )}
                </button>
              </div>
            </div>
          </div>
        </div>
      )}
    </Layout>
  );
}

export async function getServerSideProps({ locale }) {
  // Auth check is handled client-side via useEffect + useAuth hook
  // Cannot check cookies server-side because backend and frontend are on different domains
  return {
    props: {
      ...(await serverSideTranslations(locale, ['agents', 'common', 'errors'])),
    },
  };
}
