import { useState, useEffect, useCallback, useMemo } from "react";
import { useRouter } from "next/router";
import toast, { Toaster } from "react-hot-toast";
import {
  ArrowLeft, Bot, MessageCircle, Save, Camera, Trash2, Plus,
  Upload, Loader2, FileText, Database, Link, Zap, Users, TrendingUp,
  LogOut, UserCircle, Mail, ChevronDown, ChevronUp, Hash, Copy, CheckCircle, XCircle, Send, RefreshCw
} from "lucide-react";
import { useTranslation } from 'next-i18next';
import { serverSideTranslations } from 'next-i18next/serverSideTranslations';
import Layout from '../components/Layout';
import { useAuth } from '../hooks/useAuth';
import api from '../lib/api';

const AGENT_TYPES_CONFIG = {
  conversationnel: { key: 'conversationnel', icon: Users, color: 'bg-blue-500', gradient: 'from-blue-500 to-blue-600' },
  recherche_live: { key: 'recherche_live', icon: TrendingUp, color: 'bg-purple-500', gradient: 'from-purple-500 to-violet-600' }
};

// Collapsible section wrapper
function Section({ icon: Icon, title, subtitle, color, children, defaultOpen = false }) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <div className="bg-white rounded-card shadow-card border border-gray-200 overflow-hidden transition-all duration-200 hover:shadow-elevated">
      <button
        type="button"
        onClick={() => setOpen(o => !o)}
        className="w-full flex items-center justify-between px-6 py-4 text-left hover:bg-gray-50/50 transition-colors"
      >
        <div className="flex items-center space-x-3">
          <div className={`p-2 rounded-xl ${color || 'bg-blue-100'}`}>
            <Icon className={`w-5 h-5 ${color ? 'text-white' : 'text-blue-600'}`} />
          </div>
          <div>
            <h3 className="font-heading font-bold text-gray-900">{title}</h3>
            {subtitle && <p className="text-xs text-gray-500 mt-0.5">{subtitle}</p>}
          </div>
        </div>
        {open ? <ChevronUp className="w-5 h-5 text-gray-400" /> : <ChevronDown className="w-5 h-5 text-gray-400" />}
      </button>
      {open && <div className="px-6 pb-6 border-t border-gray-100 pt-4">{children}</div>}
    </div>
  );
}

export default function CompanionSettings() {
  const { t } = useTranslation(['agents', 'common', 'errors']);
  const router = useRouter();
  const urlAgentId = router.query.agentId;
  const { user, loading: authLoading, authenticated, logout: authLogout } = useAuth();

  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [currentAgent, setCurrentAgent] = useState(null);

  // Form state
  const [form, setForm] = useState({
    name: "", contexte: "", biographie: "", profile_photo: null,
    type: 'conversationnel',
    email_tags: [], neo4j_enabled: false, neo4j_person_name: "",
    neo4j_depth: 1, weekly_recap_enabled: false, weekly_recap_prompt: "",
    weekly_recap_recipients: []
  });
  const [emailTagInput, setEmailTagInput] = useState("");

  // Documents
  const [agentDocuments, setAgentDocuments] = useState([]);
  const [uploadingDoc, setUploadingDoc] = useState(false);
  const [isDragging, setIsDragging] = useState(false);

  // Traceability docs
  const [traceabilityDocs, setTraceabilityDocs] = useState([]);
  const [uploadingTraceabilityDoc, setUploadingTraceabilityDoc] = useState(false);
  const [isDraggingTraceability, setIsDraggingTraceability] = useState(false);

  // Notion
  const [notionLinks, setNotionLinks] = useState([]);
  const [notionInput, setNotionInput] = useState("");
  const [notionType, setNotionType] = useState("page");
  const [addingNotionLink, setAddingNotionLink] = useState(false);
  const [ingestingNotionLinkId, setIngestingNotionLinkId] = useState(null);
  const [resyncingDocId, setResyncingDocId] = useState(null);

  // Slack
  const [slackConfig, setSlackConfig] = useState({ is_configured: false, team_id: '', bot_user_id: '', masked_token: '', masked_secret: '' });
  const [slackForm, setSlackForm] = useState({ bot_token: '', signing_secret: '' });
  const [savingSlack, setSavingSlack] = useState(false);
  const [testingSlack, setTestingSlack] = useState(false);
  const [sendingRecap, setSendingRecap] = useState(false);
  const [recapRecipientInput, setRecapRecipientInput] = useState("");

  // Neo4j
  const [neo4jPersons, setNeo4jPersons] = useState([]);
  const [userCompany, setUserCompany] = useState(null);

  const AGENT_TYPES = useMemo(() => ({
    conversationnel: { ...AGENT_TYPES_CONFIG.conversationnel, name: t('agents:types.conversationnel.name'), description: t('agents:types.conversationnel.description') },
    recherche_live: { ...AGENT_TYPES_CONFIG.recherche_live, name: t('agents:types.recherche_live.name'), description: t('agents:types.recherche_live.description') }
  }), [t]);

  // --- Data loading ---
  const loadAgentData = useCallback(async (agentId) => {
    try {
      const agentRes = await api.get(`/agents/${agentId}`);
      const agent = agentRes.data.agent;
      if (!agent) { router.push("/agents"); return; }

      // Shared agents without edit permission → redirect straight to chat
      if (agent.shared && !agent.can_edit) { router.push(`/chat/${agentId}`); return; }

      const docsRes = await api.get(`/user/documents?agent_id=${agentId}`);

      setCurrentAgent(agent);
      setAgentDocuments(docsRes.data.documents || []);

      let parsedEmailTags = [];
      if (agent.email_tags) {
        try { parsedEmailTags = typeof agent.email_tags === 'string' ? JSON.parse(agent.email_tags) : agent.email_tags; }
        catch { parsedEmailTags = []; }
      }

      setForm({
        name: agent.name || "", contexte: agent.contexte || "", biographie: agent.biographie || "",
        profile_photo: null,
        type: agent.type || 'conversationnel',
        email_tags: parsedEmailTags, neo4j_enabled: agent.neo4j_enabled || false,
        neo4j_person_name: agent.neo4j_person_name || "", neo4j_depth: agent.neo4j_depth || 1,
        weekly_recap_enabled: agent.weekly_recap_enabled || false,
        weekly_recap_prompt: agent.weekly_recap_prompt || "",
        weekly_recap_recipients: agent.weekly_recap_recipients ? JSON.parse(agent.weekly_recap_recipients) : []
      });
    } catch (error) {
      toast.error(t('agents:toast.loadError'));
      router.push("/agents");
    } finally {
      setLoading(false);
    }
  }, [router, t]);

  const loadTraceabilityDocs = useCallback(async (agentId) => {
    try {
      const res = await api.get(`/api/agents/${agentId}/traceability-docs`);
      setTraceabilityDocs(res.data.documents || []);
    } catch { setTraceabilityDocs([]); }
  }, []);

  const loadNotionLinks = useCallback(async (agentId) => {
    try {
      const res = await api.get(`/api/agents/${agentId}/notion-links`);
      setNotionLinks(res.data.links || []);
    } catch { setNotionLinks([]); }
  }, []);

  const loadNeo4jData = useCallback(async () => {
    try {
      const [companyRes, personsRes] = await Promise.all([
        api.get(`/api/companies/mine`),
        api.get(`/api/neo4j/persons`)
      ]);
      setUserCompany(companyRes.data.company);
      setNeo4jPersons(personsRes.data.persons || []);
    } catch { /* Neo4j is optional */ }
  }, []);

  const loadSlackConfig = useCallback(async (agentId) => {
    try {
      const res = await api.get(`/api/agents/${agentId}/slack-config`);
      setSlackConfig(res.data);
    } catch { setSlackConfig({ is_configured: false, team_id: '', bot_user_id: '', masked_token: '', masked_secret: '' }); }
  }, []);

  const saveSlackConfig = async () => {
    if (!slackForm.bot_token.trim() || !slackForm.signing_secret.trim()) return;
    setSavingSlack(true);
    try {
      const res = await api.put(`/api/agents/${currentAgent.id}/slack-config`,
        { slack_bot_token: slackForm.bot_token, slack_signing_secret: slackForm.signing_secret }
      );
      toast.success(t('agents:slack.saveSuccess', { team: res.data.team_name }));
      setSlackForm({ bot_token: '', signing_secret: '' });
      await loadSlackConfig(currentAgent.id);
    } catch (error) {
      toast.error(error.response?.data?.detail || t('agents:slack.saveError'));
    } finally { setSavingSlack(false); }
  };

  const testSlackConnection = async () => {
    setTestingSlack(true);
    try {
      const res = await api.post(`/api/agents/${currentAgent.id}/slack-test`, {});
      if (res.data.is_valid) {
        toast.success(t('agents:slack.testSuccess', { team: res.data.team_name, bot: res.data.bot_name }));
      } else {
        toast.error(t('agents:slack.testError', { error: res.data.error }));
      }
    } catch (error) {
      toast.error(error.response?.data?.detail || t('agents:slack.testError', { error: 'unknown' }));
    } finally { setTestingSlack(false); }
  };

  const disconnectSlack = async () => {
    if (!confirm(t('agents:slack.disconnectConfirm'))) return;
    try {
      await api.delete(`/api/agents/${currentAgent.id}/slack-config`);
      toast.success(t('agents:slack.disconnected'));
      await loadSlackConfig(currentAgent.id);
    } catch { toast.error(t('agents:slack.disconnectError')); }
  };

  const sendRecapNow = async () => {
    setSendingRecap(true);
    try {
      const res = await api.post(`/api/agents/${currentAgent.id}/recap-send`, {});
      if (res.data.status === "success") {
        toast.success(t('agents:toast.recapSendSuccess', { email: res.data.email }));
      } else if (res.data.status === "no_data") {
        toast(t('agents:toast.recapSendNoData'), { icon: 'ℹ️' });
      }
    } catch (error) {
      toast.error(error.response?.data?.detail || t('agents:toast.recapSendError'));
    } finally { setSendingRecap(false); }
  };

  useEffect(() => {
    if (!authenticated && !authLoading) {
      router.push("/login");
      return;
    }

    if (authenticated && urlAgentId) {
      loadAgentData(urlAgentId);
      loadTraceabilityDocs(urlAgentId);
      loadNotionLinks(urlAgentId);
      loadNeo4jData();
      loadSlackConfig(urlAgentId);
    } else if (authenticated && router.isReady) {
      router.push("/agents");
    }
  }, [authenticated, authLoading, urlAgentId, router.isReady]);

  // --- Actions ---
  const saveAgent = async () => {
    if (!form.name.trim()) { toast.error(t('agents:toast.nameRequired')); return; }
    setSaving(true);
    try {
      const formData = new FormData();
      formData.append("name", form.name);
      formData.append("contexte", form.contexte);
      formData.append("biographie", form.biographie);
      if (form.profile_photo) formData.append("profile_photo", form.profile_photo);
      formData.append("type", form.type || 'conversationnel');
      formData.append("email_tags", form.email_tags.length > 0 ? JSON.stringify(form.email_tags) : "[]");
      formData.append("neo4j_enabled", form.neo4j_enabled ? "true" : "false");
      if (form.neo4j_person_name) formData.append("neo4j_person_name", form.neo4j_person_name);
      formData.append("neo4j_depth", String(form.neo4j_depth || 1));
      formData.append("weekly_recap_enabled", form.weekly_recap_enabled ? "true" : "false");
      if (form.weekly_recap_prompt) formData.append("weekly_recap_prompt", form.weekly_recap_prompt);
      if (form.weekly_recap_recipients && form.weekly_recap_recipients.length > 0) {
        formData.append("weekly_recap_recipients", JSON.stringify(form.weekly_recap_recipients));
      }

      await api.put(`/agents/${currentAgent.id}`, formData, {
        headers: { "Content-Type": "multipart/form-data" }
      });
      toast.success(t('agents:toast.modifySuccess'));
      // Reload to get fresh data (including new photo URL)
      await loadAgentData(currentAgent.id);
    } catch (error) {
      const detail = error.response?.data?.detail;
      if (Array.isArray(detail)) {
        toast.error(detail.map(err => err.msg || JSON.stringify(err)).join(', '));
      } else if (typeof detail === 'string') {
        toast.error(detail);
      } else {
        toast.error(t('agents:toast.modifyError'));
      }
    } finally {
      setSaving(false);
    }
  };

  const pollUploadStatus = async (taskId, agentId) => {
    const maxAttempts = 60;
    for (let i = 0; i < maxAttempts; i++) {
      await new Promise(r => setTimeout(r, 2000));
      try {
        const res = await api.get(`/upload-status/${taskId}`);
        const { status, error } = res.data;
        if (status === 'completed') {
          toast.success(t('agents:toast.documentAdded'));
          const docs = await api.get(`/user/documents?agent_id=${agentId}`);
          setAgentDocuments(docs.data.documents || []);
          return;
        }
        if (status === 'failed') {
          toast.error(error || t('agents:toast.documentAddError'));
          return;
        }
      } catch { /* keep polling */ }
    }
    toast.error(t('agents:toast.documentAddError'));
  };

  const uploadDocument = async (file) => {
    setUploadingDoc(true);
    try {
      const fd = new FormData();
      fd.append("file", file);
      fd.append("agent_id", currentAgent.id);
      const response = await api.post(`/upload-agent`, fd, {
        headers: { 'Content-Type': 'multipart/form-data' }
      });
      const data = response.data;
      if (data.status === 'processing' && data.task_id) {
        toast(t('agents:toast.documentProcessing', 'Document en cours de traitement...'));
        await pollUploadStatus(data.task_id, currentAgent.id);
      } else {
        toast.success(t('agents:toast.documentAdded'));
        await new Promise(r => setTimeout(r, 500));
        const res = await api.get(`/user/documents?agent_id=${currentAgent.id}`);
        setAgentDocuments(res.data.documents || []);
      }
    } catch (error) {
      toast.error(error.response?.data?.detail || t('agents:toast.documentAddError'));
    } finally { setUploadingDoc(false); }
  };

  const deleteDocument = async (docId) => {
    if (!confirm(t('agents:toast.documentDeleteConfirm'))) return;
    try {
      await api.delete(`/documents/${docId}`);
      toast.success(t('agents:toast.documentDeleted'));
      setAgentDocuments(prev => prev.filter(d => d.id !== docId));
    } catch { toast.error(t('agents:toast.deleteError')); }
  };

  const uploadTraceabilityDoc = async (file) => {
    setUploadingTraceabilityDoc(true);
    try {
      const fd = new FormData();
      fd.append("file", file);
      await api.post(`/api/agents/${currentAgent.id}/traceability-docs`, fd, {
        headers: { "Content-Type": "multipart/form-data" }
      });
      toast.success(t('agents:toast.traceabilityDocAdded'));
      await loadTraceabilityDocs(currentAgent.id);
    } catch (error) {
      toast.error(error.response?.data?.detail || t('agents:toast.traceabilityDocAddError'));
    } finally { setUploadingTraceabilityDoc(false); }
  };

  const deleteTraceabilityDoc = async (docId) => {
    if (!confirm(t('agents:toast.documentDeleteConfirm'))) return;
    try {
      await api.delete(`/api/agents/${currentAgent.id}/traceability-docs/${docId}`);
      toast.success(t('agents:toast.documentDeleted'));
      await loadTraceabilityDocs(currentAgent.id);
    } catch { toast.error(t('agents:toast.deleteError')); }
  };

  const addNotionLink = async () => {
    if (!notionInput.trim()) return;
    setAddingNotionLink(true);
    try {
      await api.post(`/api/agents/${currentAgent.id}/notion-links`,
        { url: notionInput, type: notionType }
      );
      toast.success(t('agents:toast.notionLinkAdded'));
      setNotionInput("");
      await loadNotionLinks(currentAgent.id);
    } catch (error) {
      toast.error(error.response?.data?.detail || t('agents:toast.notionLinkError'));
    } finally { setAddingNotionLink(false); }
  };

  const refreshAgentDocuments = async () => {
    try {
      const res = await api.get(`/user/documents?agent_id=${currentAgent.id}`);
      setAgentDocuments(res.data.documents || []);
    } catch { /* silent */ }
  };

  const resyncNotionDoc = async (doc) => {
    if (!doc.notion_link_id) return;
    setResyncingDocId(doc.id);
    try {
      const res = await api.post(
        `/api/agents/${currentAgent.id}/notion-links/${doc.notion_link_id}/resync`,
        {}
      );
      toast.success(t('agents:toast.notionResyncSuccess', { chunks: res.data.chunk_count }));
      await refreshAgentDocuments();
    } catch (error) {
      toast.error(error.response?.data?.detail || t('agents:toast.notionResyncError'));
    } finally {
      setResyncingDocId(null);
    }
  };

  const deleteNotionLink = async (linkId) => {
    try {
      await api.delete(`/api/agents/${currentAgent.id}/notion-links/${linkId}`);
      toast.success(t('agents:toast.notionLinkDeleted'));
      await Promise.all([loadNotionLinks(currentAgent.id), refreshAgentDocuments()]);
    } catch { toast.error(t('agents:toast.deleteError')); }
  };

  const ingestNotionLink = async (linkId) => {
    try {
      setIngestingNotionLinkId(linkId);
      const res = await api.post(`/api/agents/${currentAgent.id}/notion-links/${linkId}/ingest`, {});
      toast.success(t('agents:toast.notionIngestSuccess', { chunks: res.data.chunk_count }));
      await Promise.all([loadNotionLinks(currentAgent.id), refreshAgentDocuments()]);
    } catch (error) {
      if (error.response?.status === 409) {
        toast.error(t('agents:toast.notionAlreadyIngested'));
      } else {
        toast.error(error.response?.data?.detail || t('agents:toast.notionIngestError'));
      }
    } finally { setIngestingNotionLinkId(null); }
  };

  const handleFileDrop = (e, type) => {
    e.preventDefault();
    e.stopPropagation();
    if (type === 'rag') setIsDragging(false);
    else setIsDraggingTraceability(false);

    const files = e.dataTransfer.files;
    if (!files || files.length === 0) return;
    const file = files[0];
    const ext = '.' + file.name.split('.').pop().toLowerCase();

    if (type === 'rag') {
      if (['.pdf', '.txt', '.doc', '.docx'].includes(ext)) uploadDocument(file);
      else toast.error(t('agents:toast.unsupportedFormat'));
    } else {
      if (['.pdf', '.txt', '.docx', '.xlsx', '.xls', '.csv'].includes(ext)) uploadTraceabilityDoc(file);
      else toast.error(t('agents:toast.unsupportedTraceabilityFormat'));
    }
  };

  const logout = () => {
    authLogout();
  };

  // --- Loading state ---
  if (authLoading || loading || !currentAgent) {
    return (
      <div className="min-h-screen bg-gray-50 flex items-center justify-center">
        <div className="text-center">
          <Loader2 className="w-12 h-12 text-blue-600 animate-spin mx-auto mb-4" />
          <p className="text-gray-500 font-medium">{t('agents:loading')}</p>
        </div>
      </div>
    );
  }

  const typeConfig = AGENT_TYPES[currentAgent.type] || AGENT_TYPES.conversationnel;
  const apiUrl = process.env.NEXT_PUBLIC_API_URL || (typeof window !== "undefined" && window.location.hostname.includes("run.app") ? window.location.origin.replace("frontend", "backend") : "http://localhost:8080");
  const profilePhotoUrl = form.profile_photo
    ? URL.createObjectURL(form.profile_photo)
    : currentAgent.profile_photo
      ? (currentAgent.profile_photo.startsWith('http') ? currentAgent.profile_photo : `${apiUrl}/profile_photos/${currentAgent.profile_photo.replace(/^.*[\\/]/, '')}`)
      : null;

  return (
    <Layout
      showBack
      backHref="/agents"
      title={currentAgent?.name || ''}
      onLogout={logout}
      actions={currentAgent && (
        <button
          onClick={() => router.push(`/chat/${currentAgent.id}`)}
          className="flex items-center space-x-2 px-4 py-2 bg-gradient-to-r from-blue-600 to-purple-600 hover:from-blue-700 hover:to-purple-700 text-white rounded-button font-semibold shadow-card hover:shadow-elevated transition-all mr-2"
        >
          <MessageCircle className="w-4 h-4" />
          <span className="hidden sm:inline">{t('agents:settings.openChat')}</span>
        </button>
      )}
    >
      <Toaster position="top-right" />

      {/* ─── Hero: Profile Photo + Name + Key Info ─── */}
      <div className="relative overflow-hidden">
        {/* Gradient banner */}
        <div className={`h-40 bg-gradient-to-r ${AGENT_TYPES_CONFIG[currentAgent.type]?.gradient || 'from-blue-500 to-purple-600'} relative`}>
          <div className="absolute inset-0 opacity-10">
            <div className="absolute top-0 left-1/4 w-64 h-64 bg-white rounded-full mix-blend-overlay filter blur-2xl animate-blob"></div>
            <div className="absolute bottom-0 right-1/4 w-64 h-64 bg-white rounded-full mix-blend-overlay filter blur-2xl animate-blob animation-delay-2000"></div>
          </div>
        </div>

        <div className="max-w-5xl mx-auto px-4 sm:px-6 lg:px-8 -mt-20 relative z-10">
          <div className="bg-white rounded-card shadow-elevated border border-gray-200 p-6 sm:p-8">
            <div className="flex flex-col sm:flex-row items-center sm:items-end gap-6">
              {/* Profile Photo */}
              <div className="relative group flex-shrink-0">
                {profilePhotoUrl ? (
                  <img
                    src={profilePhotoUrl}
                    alt={form.name}
                    className="w-32 h-32 rounded-card object-cover border-4 border-white shadow-elevated ring-4 ring-blue-100"
                    onError={e => { e.target.onerror = null; e.target.src = '/default-avatar.svg'; }}
                  />
                ) : (
                  <div className={`w-32 h-32 rounded-card ${typeConfig.color} flex items-center justify-center border-4 border-white shadow-elevated ring-4 ring-blue-100`}>
                    <Bot className="w-16 h-16 text-white" />
                  </div>
                )}
                <label className="absolute inset-0 rounded-2xl bg-black/40 opacity-0 group-hover:opacity-100 transition-opacity cursor-pointer flex items-center justify-center">
                  <Camera className="w-8 h-8 text-white" />
                  <input
                    type="file"
                    accept="image/*"
                    className="hidden"
                    onChange={e => {
                      if (e.target.files?.[0]) setForm(f => ({ ...f, profile_photo: e.target.files[0] }));
                    }}
                  />
                </label>
              </div>

              {/* Name + Info */}
              <div className="flex-1 text-center sm:text-left w-full">
                <input
                  type="text"
                  value={form.name}
                  onChange={e => setForm(f => ({ ...f, name: e.target.value }))}
                  className="text-3xl font-bold text-gray-900 bg-transparent border-none outline-none w-full placeholder-gray-300 focus:ring-0"
                  placeholder={t('agents:form.name.placeholder')}
                />
                <div className="flex flex-wrap items-center gap-2 mt-2">
                  <span className={`inline-flex items-center px-3 py-1 ${typeConfig.color} text-white text-xs font-semibold rounded-full shadow-sm`}>
                    <typeConfig.icon className="w-3 h-3 mr-1" />
                    {typeConfig.name}
                  </span>
                  {form.neo4j_enabled && (
                    <span className="inline-flex items-center px-3 py-1 bg-teal-500 text-white text-xs font-semibold rounded-full shadow-sm">
                      <Database className="w-3 h-3 mr-1" /> Neo4j
                    </span>
                  )}
                  {form.weekly_recap_enabled && (
                    <span className="inline-flex items-center px-3 py-1 bg-amber-500 text-white text-xs font-semibold rounded-full shadow-sm">
                      <Mail className="w-3 h-3 mr-1" /> Recap
                    </span>
                  )}
                </div>
              </div>

              {/* Save button - desktop */}
              <div className="hidden sm:block flex-shrink-0">
                <button
                  onClick={saveAgent}
                  disabled={saving}
                  className="flex items-center space-x-2 px-6 py-3 bg-gradient-to-r from-blue-600 to-purple-600 hover:from-blue-700 hover:to-purple-700 text-white rounded-button font-semibold shadow-card hover:shadow-elevated transition-all disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  {saving ? <Loader2 className="w-5 h-5 animate-spin" /> : <Save className="w-5 h-5" />}
                  <span>{saving ? t('agents:buttons.modifying') : t('agents:settings.save')}</span>
                </button>
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* ─── Settings Sections ─── */}
      <div className="max-w-5xl mx-auto px-4 sm:px-6 lg:px-8 py-8 space-y-6">

        {/* Identity & Personality */}
        <Section
          icon={Bot}
          title={t('agents:settings.identity')}
          subtitle={t('agents:settings.identityDesc')}
          color="bg-blue-500"
        >
          <div className="space-y-4">
            <div>
              <label className="text-sm font-semibold text-gray-700 mb-1 block">{t('agents:form.context.placeholder')}</label>
              <textarea
                className="w-full px-4 py-3 border border-gray-200 rounded-input focus:border-blue-500 focus:ring-2 focus:ring-blue-200 transition-all outline-none bg-white resize-y"
                rows="4"
                value={form.contexte}
                onChange={e => setForm(f => ({ ...f, contexte: e.target.value }))}
              />
            </div>
            <div>
              <label className="text-sm font-semibold text-gray-700 mb-1 block">{t('agents:form.biography.placeholder')}</label>
              <textarea
                className="w-full px-4 py-3 border border-gray-200 rounded-input focus:border-blue-500 focus:ring-2 focus:ring-blue-200 transition-all outline-none bg-white resize-y"
                rows="3"
                value={form.biographie}
                onChange={e => setForm(f => ({ ...f, biographie: e.target.value }))}
              />
            </div>
          </div>
        </Section>

        {/* Configuration: Type, Provider, Status, Email Tags */}
        <Section
          icon={Zap}
          title={t('agents:settings.configuration')}
          subtitle={t('agents:settings.configurationDesc')}
          color="bg-purple-500"
        >
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {/* Type */}
            <div>
              <label className="text-sm font-semibold text-gray-700 mb-2 block flex items-center">
                <Zap className="w-4 h-4 mr-2 text-purple-600" />
                {t('agents:form.type.label')}
              </label>
              <select
                className="w-full px-4 py-3 border border-gray-200 rounded-input focus:border-purple-500 focus:ring-2 focus:ring-purple-200 transition-all outline-none bg-white font-medium"
                value={form.type}
                onChange={e => setForm(f => ({ ...f, type: e.target.value }))}
              >
                {Object.keys(AGENT_TYPES).map(key => (
                  <option key={key} value={AGENT_TYPES[key].key}>
                    {AGENT_TYPES[key].name} - {AGENT_TYPES[key].description}
                  </option>
                ))}
              </select>
            </div>

          </div>

          {/* Email Tags */}
          <div className="mt-4">
            <label className="text-sm font-semibold text-gray-700 mb-2 block flex items-center">
              <MessageCircle className="w-4 h-4 mr-2 text-purple-600" />
              {t('agents:form.emailTags.label')}
            </label>
            <div className="flex flex-wrap gap-2 mb-2">
              {(form.email_tags || []).map((tag, index) => (
                <span key={index} className="inline-flex items-center px-3 py-1 bg-purple-100 text-purple-700 rounded-full text-sm font-medium">
                  {tag}
                  <button type="button" onClick={() => setForm(f => ({ ...f, email_tags: f.email_tags.filter((_, i) => i !== index) }))} className="ml-2 text-purple-500 hover:text-purple-700">
                    &times;
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
                    if (!form.email_tags.includes(newTag)) setForm(f => ({ ...f, email_tags: [...(f.email_tags || []), newTag] }));
                    setEmailTagInput("");
                  }
                }}
              />
              <button
                type="button"
                onClick={() => {
                  if (emailTagInput.trim()) {
                    const newTag = `@${emailTagInput.trim().toLowerCase().replace(/^@/, '')}`;
                    if (!form.email_tags.includes(newTag)) setForm(f => ({ ...f, email_tags: [...(f.email_tags || []), newTag] }));
                    setEmailTagInput("");
                  }
                }}
                className="px-4 py-2 bg-purple-600 text-white rounded-xl hover:bg-purple-700 transition-colors text-sm font-medium"
              >
                {t('agents:buttons.addTag')}
              </button>
            </div>
            <p className="text-xs text-gray-500 mt-1">{t('agents:form.emailTags.helpText')}</p>
          </div>
        </Section>

        {/* Neo4j Knowledge Graph */}
        {userCompany && userCompany.neo4j_enabled && (
          <Section
            icon={Database}
            title={t('agents:form.neo4j.label')}
            subtitle={t('agents:settings.neo4jDesc')}
            color="bg-teal-500"
          >
            <div className="flex items-center justify-between mb-4 p-3 bg-teal-50 rounded-xl border border-teal-200">
              <span className="text-sm font-semibold text-gray-700">{t('agents:settings.enableNeo4j')}</span>
              <button
                type="button"
                className={`w-14 h-7 flex items-center rounded-full px-1 transition-colors duration-200 focus:outline-none border-2 ${form.neo4j_enabled ? 'bg-teal-600 border-teal-600' : 'bg-gray-200 border-gray-300'}`}
                onClick={() => setForm(f => ({ ...f, neo4j_enabled: !f.neo4j_enabled }))}
              >
                <span className={`h-5 w-5 rounded-full shadow transition-transform duration-200 ${form.neo4j_enabled ? 'bg-white translate-x-7' : 'bg-gray-400 translate-x-0'}`} />
              </button>
            </div>
            {form.neo4j_enabled && (
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                <div>
                  <label className="text-sm font-medium text-gray-600 mb-1 block">{t('agents:form.neo4j.person')}</label>
                  <select
                    className="w-full px-3 py-2.5 border border-teal-200 rounded-input focus:border-teal-500 focus:ring-2 focus:ring-teal-200 transition-all outline-none bg-white text-sm"
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
                  <label className="text-sm font-medium text-gray-600 mb-1 block">{t('agents:form.neo4j.depth')}</label>
                  <select
                    className="w-full px-3 py-2.5 border border-teal-200 rounded-input focus:border-teal-500 focus:ring-2 focus:ring-teal-200 transition-all outline-none bg-white text-sm"
                    value={form.neo4j_depth}
                    onChange={e => setForm(f => ({ ...f, neo4j_depth: parseInt(e.target.value) }))}
                  >
                    <option value={1}>{t('agents:form.neo4j.depth1')}</option>
                    <option value={2}>{t('agents:form.neo4j.depth2')}</option>
                  </select>
                </div>
              </div>
            )}
          </Section>
        )}

        {/* RAG Documents */}
        <Section
          icon={FileText}
          title={t('agents:documents.title', { count: agentDocuments.length })}
          subtitle={t('agents:settings.ragDocsDesc')}
          color="bg-purple-500"
        >
          {/* Drop zone */}
          <div
            className={`relative border-2 border-dashed rounded-xl p-8 mb-4 transition-all duration-300 text-center ${
              isDragging ? 'border-purple-500 bg-purple-50 scale-[1.01]' : 'border-gray-300 bg-gradient-to-br from-gray-50 to-purple-50/50 hover:border-purple-400'
            }`}
            onDragOver={e => { e.preventDefault(); e.stopPropagation(); setIsDragging(true); }}
            onDragEnter={e => { e.preventDefault(); e.stopPropagation(); setIsDragging(true); }}
            onDragLeave={e => { e.preventDefault(); e.stopPropagation(); setIsDragging(false); }}
            onDrop={e => handleFileDrop(e, 'rag')}
          >
            <div className={`p-4 rounded-full inline-flex mb-3 transition-all ${isDragging ? 'bg-purple-200 scale-110' : 'bg-purple-100'}`}>
              <Upload className={`w-8 h-8 ${isDragging ? 'text-purple-700' : 'text-purple-500'}`} />
            </div>
            <p className="font-semibold text-gray-700 mb-1">
              {isDragging ? t('agents:documents.dropHere') : t('agents:documents.dragDrop')}
            </p>
            <p className="text-xs text-gray-500 mb-3">{t('agents:documents.formats')}</p>
            <label className="cursor-pointer inline-flex items-center space-x-2 px-4 py-2 bg-gradient-to-r from-purple-600 to-blue-600 text-white rounded-lg hover:from-purple-700 hover:to-blue-700 transition-all font-medium text-sm shadow-card hover:shadow-elevated">
              <input type="file" className="hidden" accept=".pdf,.txt,.doc,.docx" disabled={uploadingDoc}
                onChange={e => { if (e.target.files?.[0]) { uploadDocument(e.target.files[0]); e.target.value = ''; } }} />
              {uploadingDoc ? <><Loader2 className="w-4 h-4 animate-spin" /><span>{t('agents:buttons.uploading')}</span></> : <><Plus className="w-4 h-4" /><span>{t('agents:buttons.clickToChoose')}</span></>}
            </label>
          </div>

          {/* Documents list */}
          <div className="space-y-2 max-h-64 overflow-y-auto">
            {agentDocuments.length === 0 ? (
              <div className="text-center py-6 text-gray-400">
                <FileText className="w-10 h-10 mx-auto mb-2 opacity-50" />
                <p className="text-sm">{t('agents:documents.noDocuments')}</p>
              </div>
            ) : agentDocuments.map(doc => (
              <div key={doc.id} className="flex items-center justify-between p-3 bg-white rounded-xl border border-gray-200 hover:border-purple-300 transition-all group">
                <div className="flex items-center space-x-3 flex-1 min-w-0">
                  <FileText className="w-5 h-5 text-purple-600 flex-shrink-0" />
                  <div className="flex-1 min-w-0">
                    <p className="text-sm font-medium text-gray-900 truncate">{doc.filename}</p>
                    <p className="text-xs text-gray-500">{new Date(doc.created_at).toLocaleDateString('fr-FR')}</p>
                  </div>
                  {doc.notion_link_id && (
                    <span className="px-2 py-0.5 text-xs rounded-full bg-indigo-50 text-indigo-600 border border-indigo-200 flex-shrink-0">Notion</span>
                  )}
                </div>
                <div className="flex items-center space-x-1">
                  {doc.notion_link_id && (
                    <button
                      onClick={() => resyncNotionDoc(doc)}
                      disabled={resyncingDocId === doc.id}
                      className="p-2 text-gray-400 hover:text-indigo-600 hover:bg-indigo-50 rounded-lg transition-all opacity-0 group-hover:opacity-100 disabled:opacity-100"
                      title={t('agents:buttons.resyncNotion')}
                    >
                      {resyncingDocId === doc.id ? <Loader2 className="w-4 h-4 animate-spin text-indigo-500" /> : <RefreshCw className="w-4 h-4" />}
                    </button>
                  )}
                  <button onClick={() => deleteDocument(doc.id)} className="p-2 text-gray-400 hover:text-red-600 hover:bg-red-50 rounded-lg transition-all opacity-0 group-hover:opacity-100" title={t('agents:buttons.delete')}>
                    <Trash2 className="w-4 h-4" />
                  </button>
                </div>
              </div>
            ))}
          </div>
        </Section>

        {/* Traceability Documents */}
        <Section
          icon={FileText}
          title={t('agents:traceabilityDocs.title', { count: traceabilityDocs.length })}
          subtitle={t('agents:settings.traceabilityDesc')}
          color="bg-amber-500"
          defaultOpen={false}
        >
          {/* Drop zone */}
          <div
            className={`relative border-2 border-dashed rounded-xl p-8 mb-4 transition-all duration-300 text-center ${
              isDraggingTraceability ? 'border-amber-500 bg-amber-50 scale-[1.01]' : 'border-gray-300 bg-gradient-to-br from-gray-50 to-amber-50/50 hover:border-amber-400'
            }`}
            onDragOver={e => { e.preventDefault(); e.stopPropagation(); setIsDraggingTraceability(true); }}
            onDragEnter={e => { e.preventDefault(); e.stopPropagation(); setIsDraggingTraceability(true); }}
            onDragLeave={e => { e.preventDefault(); e.stopPropagation(); setIsDraggingTraceability(false); }}
            onDrop={e => handleFileDrop(e, 'traceability')}
          >
            <div className={`p-4 rounded-full inline-flex mb-3 transition-all ${isDraggingTraceability ? 'bg-amber-200 scale-110' : 'bg-amber-100'}`}>
              <Upload className={`w-8 h-8 ${isDraggingTraceability ? 'text-amber-700' : 'text-amber-500'}`} />
            </div>
            <p className="font-semibold text-gray-700 mb-1">
              {isDraggingTraceability ? t('agents:documents.dropHere') : t('agents:traceabilityDocs.dragDrop')}
            </p>
            <p className="text-xs text-gray-500 mb-3">{t('agents:traceabilityDocs.formats')}</p>
            <label className="cursor-pointer inline-flex items-center space-x-2 px-4 py-2 bg-gradient-to-r from-amber-500 to-orange-500 text-white rounded-lg hover:from-amber-600 hover:to-orange-600 transition-all font-medium text-sm shadow-card hover:shadow-elevated">
              <input type="file" className="hidden" accept=".pdf,.txt,.docx,.xlsx,.xls,.csv" disabled={uploadingTraceabilityDoc}
                onChange={e => { if (e.target.files?.[0]) { uploadTraceabilityDoc(e.target.files[0]); e.target.value = ''; } }} />
              {uploadingTraceabilityDoc ? <><Loader2 className="w-4 h-4 animate-spin" /><span>{t('agents:buttons.uploading')}</span></> : <><Plus className="w-4 h-4" /><span>{t('agents:buttons.clickToChoose')}</span></>}
            </label>
          </div>

          {/* Documents list */}
          <div className="space-y-2 max-h-64 overflow-y-auto">
            {traceabilityDocs.length === 0 ? (
              <div className="text-center py-6 text-gray-400">
                <FileText className="w-10 h-10 mx-auto mb-2 opacity-50" />
                <p className="text-sm">{t('agents:traceabilityDocs.noDocuments')}</p>
              </div>
            ) : traceabilityDocs.map(doc => (
              <div key={doc.id} className="flex items-center justify-between p-3 bg-white rounded-xl border border-gray-200 hover:border-amber-300 transition-all group">
                <div className="flex items-center space-x-3 flex-1 min-w-0">
                  <FileText className="w-5 h-5 text-amber-600 flex-shrink-0" />
                  <div className="flex-1 min-w-0">
                    <p className="text-sm font-medium text-gray-900 truncate">{doc.filename}</p>
                    <p className="text-xs text-gray-500">{new Date(doc.created_at).toLocaleDateString('fr-FR')}</p>
                  </div>
                </div>
                <button onClick={() => deleteTraceabilityDoc(doc.id)} className="p-2 text-gray-400 hover:text-red-600 hover:bg-red-50 rounded-lg transition-all opacity-0 group-hover:opacity-100" title={t('agents:buttons.delete')}>
                  <Trash2 className="w-4 h-4" />
                </button>
              </div>
            ))}
          </div>

          {/* Weekly Recap */}
          <div className="mt-6 p-4 bg-gradient-to-br from-amber-50 to-orange-50 rounded-xl border border-amber-200">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-sm font-semibold text-gray-700 flex items-center">
                  <Mail className="w-4 h-4 mr-2 text-amber-600" />
                  {t('agents:form.weeklyRecap.label')}
                </p>
                <p className="text-xs text-gray-500 mt-0.5">{t('agents:form.weeklyRecap.helpText')}</p>
              </div>
              <button
                type="button"
                className={`w-14 h-7 flex items-center rounded-full px-1 transition-colors duration-200 focus:outline-none border-2 flex-shrink-0 ml-4 ${form.weekly_recap_enabled ? 'bg-amber-500 border-amber-500' : 'bg-gray-200 border-gray-300'}`}
                onClick={() => setForm(f => ({ ...f, weekly_recap_enabled: !f.weekly_recap_enabled }))}
              >
                <span className={`h-5 w-5 rounded-full shadow transition-transform duration-200 ${form.weekly_recap_enabled ? 'bg-white translate-x-7' : 'bg-gray-400 translate-x-0'}`} />
              </button>
            </div>
            {form.weekly_recap_enabled && (
              <>
                <div className="mt-3">
                  <label className="text-xs font-semibold text-gray-600 mb-1 block">
                    {t('agents:form.weeklyRecap.promptLabel')}
                  </label>
                  <textarea
                    className="w-full px-3 py-2 border border-amber-200 rounded-lg focus:border-amber-500 focus:ring-2 focus:ring-amber-200 transition-all outline-none bg-white text-sm resize-y"
                    rows={4}
                    placeholder={t('agents:form.weeklyRecap.promptPlaceholder')}
                    value={form.weekly_recap_prompt}
                    onChange={e => setForm(f => ({ ...f, weekly_recap_prompt: e.target.value }))}
                  />
                  <p className="text-xs text-gray-400 mt-1">{t('agents:form.weeklyRecap.promptHelpText')}</p>
                </div>
                {/* Recipients */}
                <div className="mt-3">
                  <label className="text-xs font-semibold text-gray-600 mb-1 block">
                    <Users className="w-3.5 h-3.5 inline mr-1 text-amber-600" />
                    {t('agents:form.weeklyRecap.recipientsLabel')}
                  </label>
                  <div className="flex gap-2">
                    <input
                      type="email"
                      className="flex-1 px-3 py-1.5 border border-amber-200 rounded-lg focus:border-amber-500 focus:ring-2 focus:ring-amber-200 transition-all outline-none bg-white text-sm"
                      placeholder={t('agents:form.weeklyRecap.recipientsPlaceholder')}
                      value={recapRecipientInput}
                      onChange={e => setRecapRecipientInput(e.target.value)}
                      onKeyDown={e => {
                        if (e.key === 'Enter') {
                          e.preventDefault();
                          const email = recapRecipientInput.trim();
                          if (email && /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email) && !form.weekly_recap_recipients.includes(email)) {
                            setForm(f => ({ ...f, weekly_recap_recipients: [...f.weekly_recap_recipients, email] }));
                            setRecapRecipientInput("");
                          }
                        }
                      }}
                    />
                    <button
                      type="button"
                      onClick={() => {
                        const email = recapRecipientInput.trim();
                        if (email && /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email) && !form.weekly_recap_recipients.includes(email)) {
                          setForm(f => ({ ...f, weekly_recap_recipients: [...f.weekly_recap_recipients, email] }));
                          setRecapRecipientInput("");
                        }
                      }}
                      className="px-3 py-1.5 bg-amber-500 hover:bg-amber-600 text-white text-sm rounded-lg transition-colors"
                    >
                      <Plus className="w-4 h-4" />
                    </button>
                  </div>
                  <p className="text-xs text-gray-400 mt-1">{t('agents:form.weeklyRecap.recipientsHelpText')}</p>
                  {form.weekly_recap_recipients.length > 0 && (
                    <div className="flex flex-wrap gap-1.5 mt-2">
                      {form.weekly_recap_recipients.map((email, i) => (
                        <span key={i} className="inline-flex items-center gap-1 px-2 py-1 bg-amber-100 text-amber-800 text-xs rounded-full">
                          <Mail className="w-3 h-3" />
                          {email}
                          <button
                            type="button"
                            onClick={() => setForm(f => ({ ...f, weekly_recap_recipients: f.weekly_recap_recipients.filter((_, idx) => idx !== i) }))}
                            className="ml-0.5 hover:text-red-600 transition-colors"
                          >
                            <XCircle className="w-3.5 h-3.5" />
                          </button>
                        </span>
                      ))}
                    </div>
                  )}
                </div>
                {currentAgent && (
                  <button
                    type="button"
                    onClick={sendRecapNow}
                    disabled={sendingRecap}
                    className="mt-3 w-full flex items-center justify-center gap-2 px-4 py-2 bg-amber-500 hover:bg-amber-600 disabled:bg-amber-300 text-white text-sm font-medium rounded-lg transition-colors"
                  >
                    {sendingRecap ? <Loader2 className="w-4 h-4 animate-spin" /> : <Send className="w-4 h-4" />}
                    {sendingRecap ? t('agents:buttons.sendingRecap') : t('agents:buttons.sendRecapNow')}
                  </button>
                )}
              </>
            )}
          </div>
        </Section>

        {/* Notion Links */}
        <Section
          icon={Link}
          title={t('agents:notion.title', { count: notionLinks.length })}
          subtitle={t('agents:settings.notionDesc')}
          color="bg-indigo-500"
          defaultOpen={false}
        >
          {/* Add Notion link form */}
          <div className="p-4 bg-gradient-to-br from-indigo-50 to-violet-50 rounded-xl border border-indigo-200 mb-4">
            <input
              type="text"
              className="w-full px-4 py-2.5 border border-indigo-200 rounded-input focus:border-indigo-500 focus:ring-2 focus:ring-indigo-200 transition-all outline-none bg-white text-sm mb-3"
              placeholder={t('agents:notion.placeholder')}
              value={notionInput}
              onChange={e => setNotionInput(e.target.value)}
              onKeyDown={e => { if (e.key === 'Enter' && notionInput.trim()) { e.preventDefault(); addNotionLink(); } }}
            />
            <div className="flex gap-2">
              <select
                className="flex-1 px-3 py-2 border border-indigo-200 rounded-input focus:border-indigo-500 focus:ring-2 focus:ring-indigo-200 transition-all outline-none bg-white text-sm"
                value={notionType}
                onChange={e => setNotionType(e.target.value)}
              >
                <option value="page">{t('agents:notion.typePage')}</option>
                <option value="database">{t('agents:notion.typeDatabase')}</option>
              </select>
              <button
                type="button"
                onClick={addNotionLink}
                disabled={addingNotionLink || !notionInput.trim()}
                className="px-4 py-2 bg-indigo-600 text-white rounded-xl hover:bg-indigo-700 transition-colors text-sm font-medium disabled:opacity-50 disabled:cursor-not-allowed flex items-center"
              >
                {addingNotionLink ? <Loader2 className="w-4 h-4 animate-spin" /> : t('agents:notion.addButton')}
              </button>
            </div>
          </div>

          {/* Notion links list */}
          <div className="space-y-2 max-h-64 overflow-y-auto">
            {notionLinks.length === 0 ? (
              <div className="text-center py-6 text-gray-400">
                <Link className="w-10 h-10 mx-auto mb-2 opacity-50" />
                <p className="text-sm">{t('agents:notion.noLinks')}</p>
              </div>
            ) : notionLinks.map(link => (
              <div key={link.id} className="flex items-center justify-between p-3 bg-white rounded-xl border border-gray-200 hover:border-indigo-300 transition-all group">
                <div className="flex items-center space-x-3 flex-1 min-w-0">
                  <Link className="w-5 h-5 text-indigo-600 flex-shrink-0" />
                  <div className="flex-1 min-w-0">
                    <p className="text-sm font-medium text-gray-900 truncate">{link.label}</p>
                    <p className="text-xs text-gray-500">
                      {link.resource_type === 'page' ? t('agents:notion.typePage') : t('agents:notion.typeDatabase')} &middot; {new Date(link.created_at).toLocaleDateString('fr-FR')}
                    </p>
                  </div>
                </div>
                <div className="flex items-center space-x-1">
                  {link.ingested ? (
                    <span className="flex items-center space-x-1 px-2 py-1 text-xs bg-green-50 text-green-600 rounded-lg border border-green-200">
                      <CheckCircle className="w-3.5 h-3.5" />
                      <span>{t('agents:notion.ingested')}</span>
                    </span>
                  ) : (
                    <button
                      onClick={() => ingestNotionLink(link.id)}
                      disabled={ingestingNotionLinkId === link.id}
                      className="flex items-center space-x-1 px-2 py-1 text-xs text-indigo-600 hover:bg-indigo-50 rounded-lg transition-all opacity-0 group-hover:opacity-100 disabled:opacity-50"
                      title={t('agents:notion.ingestButton')}
                    >
                      {ingestingNotionLinkId === link.id ? (
                        <Loader2 className="w-3.5 h-3.5 animate-spin" />
                      ) : (
                        <>
                          <Database className="w-3.5 h-3.5" />
                          <span>{t('agents:notion.ingestButton')}</span>
                        </>
                      )}
                    </button>
                  )}
                  <button onClick={() => deleteNotionLink(link.id)} className="p-2 text-gray-400 hover:text-red-600 hover:bg-red-50 rounded-lg transition-all opacity-0 group-hover:opacity-100" title={t('agents:buttons.delete')}>
                    <Trash2 className="w-4 h-4" />
                  </button>
                </div>
              </div>
            ))}
          </div>
        </Section>

        {/* Slack Integration */}
        <Section
          icon={Hash}
          title={t('agents:slack.title')}
          subtitle={t('agents:slack.desc')}
          color="bg-pink-500"
          defaultOpen={false}
        >
          {slackConfig.is_configured ? (
            <div className="space-y-4">
              {/* Connected status */}
              <div className="flex items-center justify-between p-4 bg-gradient-to-br from-green-50 to-emerald-50 rounded-xl border border-green-200">
                <div className="flex items-center space-x-3">
                  <CheckCircle className="w-5 h-5 text-green-600" />
                  <div>
                    <p className="text-sm font-semibold text-green-800">{t('agents:slack.connected')}</p>
                    <p className="text-xs text-green-600">
                      {t('agents:slack.workspace')}: {slackConfig.team_id} &middot; {t('agents:slack.botUser')}: {slackConfig.bot_user_id}
                    </p>
                  </div>
                </div>
              </div>

              {/* Masked credentials */}
              <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                <div className="p-3 bg-gray-50 rounded-xl border border-gray-200">
                  <p className="text-xs font-medium text-gray-500 mb-1">{t('agents:slack.botToken')}</p>
                  <p className="text-sm font-mono text-gray-700">{slackConfig.masked_token}</p>
                </div>
                <div className="p-3 bg-gray-50 rounded-xl border border-gray-200">
                  <p className="text-xs font-medium text-gray-500 mb-1">{t('agents:slack.signingSecret')}</p>
                  <p className="text-sm font-mono text-gray-700">{slackConfig.masked_secret}</p>
                </div>
              </div>

              {/* Webhook URL */}
              <div className="p-4 bg-gradient-to-br from-pink-50 to-purple-50 rounded-xl border border-pink-200">
                <p className="text-xs font-medium text-gray-500 mb-1">{t('agents:slack.webhookUrl')}</p>
                <div className="flex items-center gap-2">
                  <code className="flex-1 text-sm bg-white px-3 py-2 rounded-lg border border-pink-200 text-gray-700 truncate">
                    {apiUrl}/slack/events
                  </code>
                  <button
                    type="button"
                    onClick={() => { navigator.clipboard.writeText(`${apiUrl}/slack/events`); toast.success(t('agents:slack.copied')); }}
                    className="p-2 text-pink-600 hover:bg-pink-100 rounded-lg transition-colors flex-shrink-0"
                    title="Copy"
                  >
                    <Copy className="w-4 h-4" />
                  </button>
                </div>
                <p className="text-xs text-gray-500 mt-1">{t('agents:slack.webhookHelp')}</p>
              </div>

              {/* Action buttons */}
              <div className="flex gap-3">
                <button
                  type="button"
                  onClick={testSlackConnection}
                  disabled={testingSlack}
                  className="flex-1 flex items-center justify-center space-x-2 px-4 py-2.5 bg-pink-600 text-white rounded-xl hover:bg-pink-700 transition-colors text-sm font-medium disabled:opacity-50"
                >
                  {testingSlack ? <Loader2 className="w-4 h-4 animate-spin" /> : <Zap className="w-4 h-4" />}
                  <span>{testingSlack ? t('agents:slack.testing') : t('agents:slack.test')}</span>
                </button>
                <button
                  type="button"
                  onClick={disconnectSlack}
                  className="flex items-center justify-center space-x-2 px-4 py-2.5 bg-red-100 text-red-700 rounded-xl hover:bg-red-200 transition-colors text-sm font-medium"
                >
                  <XCircle className="w-4 h-4" />
                  <span>{t('agents:slack.disconnect')}</span>
                </button>
              </div>
            </div>
          ) : (
            <div className="space-y-4">
              {/* Not connected status */}
              <div className="flex items-center space-x-3 p-3 bg-gray-50 rounded-xl border border-gray-200">
                <XCircle className="w-5 h-5 text-gray-400" />
                <p className="text-sm text-gray-500">{t('agents:slack.notConnected')}</p>
              </div>

              {/* Connection form */}
              <div className="p-4 bg-gradient-to-br from-pink-50 to-purple-50 rounded-xl border border-pink-200 space-y-3">
                <div>
                  <label className="text-sm font-medium text-gray-700 mb-1 block">{t('agents:slack.botToken')}</label>
                  <input
                    type="password"
                    className="w-full px-4 py-2.5 border border-pink-200 rounded-input focus:border-pink-500 focus:ring-2 focus:ring-pink-200 transition-all outline-none bg-white text-sm font-mono"
                    placeholder={t('agents:slack.botTokenPlaceholder')}
                    value={slackForm.bot_token}
                    onChange={e => setSlackForm(f => ({ ...f, bot_token: e.target.value }))}
                  />
                </div>
                <div>
                  <label className="text-sm font-medium text-gray-700 mb-1 block">{t('agents:slack.signingSecret')}</label>
                  <input
                    type="password"
                    className="w-full px-4 py-2.5 border border-pink-200 rounded-input focus:border-pink-500 focus:ring-2 focus:ring-pink-200 transition-all outline-none bg-white text-sm font-mono"
                    placeholder={t('agents:slack.signingSecretPlaceholder')}
                    value={slackForm.signing_secret}
                    onChange={e => setSlackForm(f => ({ ...f, signing_secret: e.target.value }))}
                  />
                </div>
                <button
                  type="button"
                  onClick={saveSlackConfig}
                  disabled={savingSlack || !slackForm.bot_token.trim() || !slackForm.signing_secret.trim()}
                  className="w-full flex items-center justify-center space-x-2 px-4 py-2.5 bg-pink-600 text-white rounded-xl hover:bg-pink-700 transition-colors text-sm font-medium disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  {savingSlack ? <Loader2 className="w-4 h-4 animate-spin" /> : <Hash className="w-4 h-4" />}
                  <span>{savingSlack ? t('agents:slack.connecting') : t('agents:slack.connect')}</span>
                </button>
              </div>

              {/* Webhook URL hint */}
              <div className="p-3 bg-gray-50 rounded-xl border border-gray-200">
                <p className="text-xs font-medium text-gray-500 mb-1">{t('agents:slack.webhookUrl')}</p>
                <div className="flex items-center gap-2">
                  <code className="flex-1 text-xs bg-white px-2 py-1.5 rounded-lg border border-gray-200 text-gray-600 truncate">
                    {apiUrl}/slack/events
                  </code>
                  <button
                    type="button"
                    onClick={() => { navigator.clipboard.writeText(`${apiUrl}/slack/events`); toast.success(t('agents:slack.copied')); }}
                    className="p-1.5 text-gray-500 hover:bg-gray-100 rounded-lg transition-colors flex-shrink-0"
                  >
                    <Copy className="w-3.5 h-3.5" />
                  </button>
                </div>
                <p className="text-xs text-gray-500 mt-1">{t('agents:slack.webhookHelp')}</p>
              </div>
            </div>
          )}
        </Section>

        {/* Mobile Save Button */}
        <div className="sm:hidden sticky bottom-4">
          <button
            onClick={saveAgent}
            disabled={saving}
            className="w-full flex items-center justify-center space-x-2 px-6 py-4 bg-gradient-to-r from-blue-600 to-purple-600 hover:from-blue-700 hover:to-purple-700 text-white rounded-button font-semibold shadow-card hover:shadow-elevated transition-all disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {saving ? <Loader2 className="w-5 h-5 animate-spin" /> : <Save className="w-5 h-5" />}
            <span>{saving ? t('agents:buttons.modifying') : t('agents:settings.save')}</span>
          </button>
        </div>

        {/* Bottom spacer */}
        <div className="h-8" />
      </div>
    </Layout>
  );
}

export async function getServerSideProps({ locale }) {
  return {
    props: {
      ...(await serverSideTranslations(locale, ['agents', 'common', 'errors'])),
    },
  };
}
