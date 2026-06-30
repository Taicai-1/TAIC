import { useState, useEffect, useCallback, useMemo, useRef } from "react";
import { useRouter } from "next/router";
import toast, { Toaster } from "react-hot-toast";
import {
  ArrowLeft, Bot, MessageCircle, Check, Camera, Trash2, Plus,
  Upload, Loader2, FileText, Database, Link, Zap, Users, TrendingUp,
  LogOut, UserCircle, Mail, ChevronDown, ChevronUp, Hash, Copy, CheckCircle, XCircle, Send, RefreshCw, HardDrive, Globe,
  Pencil, Sparkles, AlertCircle, ImageIcon, Calendar, ClipboardList, Eye, EyeOff
} from "lucide-react";
import { useTranslation } from 'next-i18next';
import { serverSideTranslations } from 'next-i18next/serverSideTranslations';
import Layout from '../components/Layout';
import { useAuth } from '../hooks/useAuth';
import api from '../lib/api';
import PluginSelector from '../components/PluginSelector';

const AGENT_TYPES_CONFIG = {
  conversationnel: { key: 'conversationnel', icon: Users, color: 'bg-blue-500', gradient: 'from-blue-500 to-blue-600' },
  recherche_live: { key: 'recherche_live', icon: TrendingUp, color: 'bg-purple-500', gradient: 'from-purple-500 to-violet-600' },
  visuel: { key: 'visuel', icon: ImageIcon, color: 'bg-pink-500', gradient: 'from-pink-500 to-pink-600' },
  actionnable: { key: 'actionnable', icon: Zap, color: 'bg-amber-500', gradient: 'from-amber-500 to-amber-600' },
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
          <div className={`p-2 rounded-button ${color || 'bg-blue-100'}`}>
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
  const [saving, setSaving] = useState(false); // kept for Slack config save
  const [currentAgent, setCurrentAgent] = useState(null);

  // Form state
  const [form, setForm] = useState({
    name: "", contexte: "", biographie: "", profile_photo: null,
    type: 'conversationnel', enabled_plugins: [],
    email_tags: [], neo4j_enabled: false, neo4j_person_name: "",
    neo4j_depth: 1, date_awareness_enabled: false, include_company_rag: false,
    company_rag_folder_ids: [],
    weekly_recap_enabled: false, weekly_recap_prompt: "",
    weekly_recap_recipients: [], recap_frequency: "weekly", recap_hour: 9,
  });
  const [emailTagInput, setEmailTagInput] = useState("");

  // Documents
  const [agentDocuments, setAgentDocuments] = useState([]);
  const [uploadingDoc, setUploadingDoc] = useState(false);
  const [uploadProgress, setUploadProgress] = useState(null); // { progress: 0-100, stage: string, filename: string }
  const [isDragging, setIsDragging] = useState(false);
  const [urlInput, setUrlInput] = useState("");
  const [addingUrl, setAddingUrl] = useState(false);
  const [refreshingDocId, setRefreshingDocId] = useState(null);
  const [agentFolders, setAgentFolders] = useState([]);
  const [uploadFolderId, setUploadFolderId] = useState(null);
  const [importingFolder, setImportingFolder] = useState(false);
  const [importProgress, setImportProgress] = useState(null); // { total, done, skipped, failed }
  const [selectedFolderId, setSelectedFolderId] = useState(null); // null = all documents
  const [collapsedFolders, setCollapsedFolders] = useState({}); // id -> true (collapsed)
  const [createParentId, setCreateParentId] = useState(null); // parent for the next created folder
  const [newFolderName, setNewFolderName] = useState('');

  // Callback ref: set the directory-picker attributes whenever the input mounts
  // (a mount-time effect misses it because the input is in a conditionally-rendered section).
  const setFolderInputRef = (el) => {
    if (el) {
      el.setAttribute('webkitdirectory', '');
      el.setAttribute('directory', '');
    }
  };

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

  // Google Drive
  const [driveLinks, setDriveLinks] = useState([]);
  const [driveInput, setDriveInput] = useState("");
  const [addingDriveLink, setAddingDriveLink] = useState(false);
  const [syncingDriveLinkId, setSyncingDriveLinkId] = useState(null);

  // Slack
  const [slackConfig, setSlackConfig] = useState({ is_configured: false, team_id: '', bot_user_id: '', masked_token: '', masked_secret: '' });
  const [slackForm, setSlackForm] = useState({ bot_token: '', signing_secret: '' });
  const [savingSlack, setSavingSlack] = useState(false);
  const [testingSlack, setTestingSlack] = useState(false);
  const [sendingRecap, setSendingRecap] = useState(false);
  const [recaps, setRecaps] = useState([]);
  const [currentRecap, setCurrentRecap] = useState(null);
  const [recapDocuments, setRecapDocuments] = useState([]);
  const [uploadingRecapDoc, setUploadingRecapDoc] = useState(false);
  const [recapForm, setRecapForm] = useState({
    name: '',
    enabled: true,
    frequency: 'weekly',
    hour: 9,
    prompt: '',
    recipients: [],
  });
  const [recapRecipientInputNew, setRecapRecipientInputNew] = useState('');
  const [showRecapCreate, setShowRecapCreate] = useState(false);
  const [loadingRecaps, setLoadingRecaps] = useState(false);
  const [savingRecap, setSavingRecap] = useState(false);
  const [sendingRecapId, setSendingRecapId] = useState(null);

  // Auto-save
  const [autoSaveStatus, setAutoSaveStatus] = useState('idle'); // 'idle' | 'saving' | 'saved' | 'error'
  const autoSaveTimer = useRef(null);
  const formLoaded = useRef(false); // prevent auto-save on initial load
  const prevFormRef = useRef(null);

  // Improve context by AI
  const [improvingContext, setImprovingContext] = useState(false);
  const [improvedContext, setImprovedContext] = useState(null);
  const [showImproveModal, setShowImproveModal] = useState(false);
  const [recapRecipientInput, setRecapRecipientInput] = useState("");

  // Company RAG folders
  const [companyFolders, setCompanyFolders] = useState([]);

  // Neo4j
  const [neo4jPersons, setNeo4jPersons] = useState([]);
  const [userCompany, setUserCompany] = useState(null);
  const [graphIngestText, setGraphIngestText] = useState("");
  const [graphIngestSource, setGraphIngestSource] = useState("");
  const [graphIngesting, setGraphIngesting] = useState(false);
  const [graphFileUploading, setGraphFileUploading] = useState(false);
  const graphFileInputRef = useRef(null);

  const AGENT_TYPES = useMemo(() => ({
    conversationnel: { ...AGENT_TYPES_CONFIG.conversationnel, name: t('agents:types.conversationnel.name'), description: t('agents:types.conversationnel.description') },
    recherche_live: { ...AGENT_TYPES_CONFIG.recherche_live, name: t('agents:types.recherche_live.name'), description: t('agents:types.recherche_live.description') },
    visuel: { ...AGENT_TYPES_CONFIG.visuel, name: t('agents:types.visuel.name'), description: t('agents:types.visuel.description') },
    actionnable: { ...AGENT_TYPES_CONFIG.actionnable, name: t('agents:types.actionnable.name'), description: t('agents:types.actionnable.description') },
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
      formLoaded.current = false; // reset so auto-save skips the next setForm

      let parsedEmailTags = [];
      if (agent.email_tags) {
        try { parsedEmailTags = typeof agent.email_tags === 'string' ? JSON.parse(agent.email_tags) : agent.email_tags; }
        catch { parsedEmailTags = []; }
      }

      let parsedPlugins = [];
      if (agent.enabled_plugins) {
        try { parsedPlugins = typeof agent.enabled_plugins === 'string' ? JSON.parse(agent.enabled_plugins) : agent.enabled_plugins; }
        catch { parsedPlugins = []; }
      }

      setForm({
        name: agent.name || "", contexte: agent.contexte || "", biographie: agent.biographie || "",
        profile_photo: null,
        type: agent.type || 'conversationnel', enabled_plugins: parsedPlugins,
        email_tags: parsedEmailTags, neo4j_enabled: agent.neo4j_enabled || false,
        neo4j_person_name: agent.neo4j_person_name || "", neo4j_depth: agent.neo4j_depth || 1,
        date_awareness_enabled: agent.date_awareness_enabled || false,
        include_company_rag: agent.include_company_rag || false,
        company_rag_folder_ids: agent.company_rag_folder_ids || [],
        weekly_recap_enabled: agent.weekly_recap_enabled || false,
        weekly_recap_prompt: agent.weekly_recap_prompt || "",
        weekly_recap_recipients: agent.weekly_recap_recipients ? JSON.parse(agent.weekly_recap_recipients) : [],
        recap_frequency: agent.recap_frequency || "weekly",
        recap_hour: agent.recap_hour !== undefined ? agent.recap_hour : 9,
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

  const loadDriveLinks = useCallback(async (agentId) => {
    try {
      const res = await api.get(`/api/agents/${agentId}/drive-links`);
      setDriveLinks(res.data.links || []);
    } catch { setDriveLinks([]); }
  }, []);

  const loadAgentFolders = useCallback(async (agentId) => {
    try {
      const res = await api.get(`/api/agents/${agentId}/folders`);
      setAgentFolders(res.data.folders || []);
    } catch { setAgentFolders([]); }
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

  const handleGraphIngest = async () => {
    if (!graphIngestText.trim() || !graphIngestSource.trim()) return;
    setGraphIngesting(true);
    try {
      const res = await api.post('/api/graph/ingest', {
        text: graphIngestText,
        source_name: graphIngestSource,
        source_type: 'document',
      });
      const data = res.data;
      if (data.nodes_created === 0 && data.relations_created === 0) {
        toast(t('agents:form.neo4j.ingestEmpty'), { icon: '🔍' });
      } else {
        toast.success(`${data.nodes_created} noeuds, ${data.relations_created} relations — ${t('agents:form.neo4j.ingestSuccess')}`);
      }
      setGraphIngestText("");
      setGraphIngestSource("");
      loadNeo4jData();
    } catch (error) {
      const detail = error?.response?.data?.detail || error?.response?.data?.message || error?.message || '';
      const status = error?.response?.status || '';
      console.error('Graph ingest error:', status, error?.response?.data, error);
      toast.error(`${t('agents:form.neo4j.ingestError')}${status ? ' (' + status + ')' : ''}${detail ? ': ' + detail : ''}`);
    } finally {
      setGraphIngesting(false);
    }
  };

  const handleGraphFileUpload = async (e) => {
    const file = e.target.files?.[0];
    if (!file) return;
    setGraphFileUploading(true);
    try {
      const formData = new FormData();
      formData.append("file", file);
      if (graphIngestSource.trim()) {
        formData.append("source_name", graphIngestSource.trim());
      }
      const res = await api.post('/api/graph/ingest-file', formData, {
        headers: { 'Content-Type': 'multipart/form-data' },
      });
      const data = res.data;
      if (data.nodes_created === 0 && data.relations_created === 0) {
        toast(t('agents:form.neo4j.ingestEmpty'), { icon: '\uD83D\uDD0D' });
      } else {
        toast.success(`${data.nodes_created} noeuds, ${data.relations_created} relations — ${t('agents:form.neo4j.ingestSuccess')}`);
      }
      setGraphIngestSource("");
      loadNeo4jData();
    } catch (error) {
      const detail = error?.response?.data?.detail || error?.response?.data?.message || error?.message || '';
      const status = error?.response?.status || '';
      console.error('Graph file ingest error:', status, error?.response?.data, error);
      toast.error(`${t('agents:form.neo4j.ingestError')}${status ? ' (' + status + ')' : ''}${detail ? ': ' + detail : ''}`);
    } finally {
      setGraphFileUploading(false);
      if (graphFileInputRef.current) graphFileInputRef.current.value = "";
    }
  };

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

  const loadRecaps = useCallback(async (agentId) => {
    if (!agentId) return;
    setLoadingRecaps(true);
    try {
      const res = await api.get(`/api/agents/${agentId}/recaps`);
      setRecaps(res.data.recaps || []);
    } catch (err) {
      console.error('Failed to load recaps:', err);
    } finally {
      setLoadingRecaps(false);
    }
  }, []);

  const loadRecapDocuments = useCallback(async (recapId) => {
    try {
      const res = await api.get(`/api/recaps/${recapId}/documents`);
      setRecapDocuments(res.data.documents || []);
    } catch (err) {
      console.error('Failed to load recap documents:', err);
    }
  }, []);

  const createRecap = async () => {
    if (!currentAgent?.id || !recapForm.name.trim()) return;
    setSavingRecap(true);
    try {
      const res = await api.post(`/api/agents/${currentAgent.id}/recaps`, {
        name: recapForm.name,
        enabled: recapForm.enabled,
        frequency: recapForm.frequency,
        hour: recapForm.hour,
        prompt: recapForm.prompt || null,
        recipients: recapForm.recipients.length > 0 ? recapForm.recipients : null,
      });
      setRecaps(prev => [...prev, res.data.recap]);
      setShowRecapCreate(false);
      setRecapForm({ name: '', enabled: true, frequency: 'weekly', hour: 9, prompt: '', recipients: [] });
    } catch (err) {
      console.error('Failed to create recap:', err);
    } finally {
      setSavingRecap(false);
    }
  };

  const updateRecap = async (recapId, updates) => {
    if (!currentAgent?.id) return;
    try {
      const res = await api.put(`/api/agents/${currentAgent.id}/recaps/${recapId}`, updates);
      setRecaps(prev => prev.map(r => r.id === recapId ? res.data.recap : r));
      if (currentRecap?.id === recapId) setCurrentRecap(res.data.recap);
    } catch (err) {
      console.error('Failed to update recap:', err);
    }
  };

  const deleteRecap = async (recapId) => {
    if (!currentAgent?.id) return;
    try {
      await api.delete(`/api/agents/${currentAgent.id}/recaps/${recapId}`);
      setRecaps(prev => prev.filter(r => r.id !== recapId));
      if (currentRecap?.id === recapId) {
        setCurrentRecap(null);
        setRecapDocuments([]);
      }
    } catch (err) {
      console.error('Failed to delete recap:', err);
    }
  };

  const uploadRecapDoc = async (recapId, file) => {
    setUploadingRecapDoc(true);
    try {
      const formData = new FormData();
      formData.append('file', file);
      await api.post(`/api/recaps/${recapId}/documents/upload`, formData, {
        headers: { 'Content-Type': 'multipart/form-data' },
      });
      await loadRecapDocuments(recapId);
      setRecaps(prev => prev.map(r => r.id === recapId ? { ...r, document_count: (r.document_count || 0) + 1 } : r));
    } catch (err) {
      console.error('Failed to upload recap document:', err);
    } finally {
      setUploadingRecapDoc(false);
    }
  };

  const removeRecapDoc = async (recapId, docId) => {
    try {
      await api.delete(`/api/recaps/${recapId}/documents/${docId}`);
      setRecapDocuments(prev => prev.filter(d => d.document_id !== docId));
      setRecaps(prev => prev.map(r => r.id === recapId ? { ...r, document_count: Math.max(0, (r.document_count || 1) - 1) } : r));
    } catch (err) {
      console.error('Failed to remove recap document:', err);
    }
  };

  const sendRecapById = async (recapId) => {
    setSendingRecapId(recapId);
    try {
      const res = await api.post(`/api/recaps/${recapId}/send`);
      if (res.data.status === 'success') {
        alert(`Recap envoyé à ${res.data.email}`);
      } else if (res.data.status === 'no_data') {
        alert('Aucune donnée pour cette période');
      }
    } catch (err) {
      console.error('Failed to send recap:', err);
      alert('Erreur lors de l\'envoi du recap');
    } finally {
      setSendingRecapId(null);
    }
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
      loadDriveLinks(urlAgentId);
      loadAgentFolders(urlAgentId);
      setUploadFolderId(null);
      loadNeo4jData();
      loadSlackConfig(urlAgentId);
      loadRecaps(urlAgentId);
      api.get('/api/company-rag/folders')
        .then(res => setCompanyFolders(res.data.folders || []))
        .catch(() => setCompanyFolders([]));
    } else if (authenticated && router.isReady) {
      router.push("/agents");
    }
  }, [authenticated, authLoading, urlAgentId, router.isReady]);

  // --- Auto-save ---
  const saveAgent = useCallback(async (formSnapshot) => {
    if (!currentAgent?.id) return;
    const f = formSnapshot || form;
    if (!f.name.trim()) return; // don't save with empty name
    setAutoSaveStatus('saving');
    try {
      const formData = new FormData();
      formData.append("name", f.name);
      formData.append("contexte", f.contexte);
      formData.append("biographie", f.biographie);
      if (f.profile_photo) formData.append("profile_photo", f.profile_photo);
      formData.append("type", f.type || 'conversationnel');
      if (f.type === 'actionnable' && f.enabled_plugins?.length > 0) {
        formData.append("enabled_plugins", JSON.stringify(f.enabled_plugins));
      }
      formData.append("email_tags", f.email_tags.length > 0 ? JSON.stringify(f.email_tags) : "[]");
      formData.append("neo4j_enabled", f.neo4j_enabled ? "true" : "false");
      if (f.neo4j_person_name) formData.append("neo4j_person_name", f.neo4j_person_name);
      formData.append("neo4j_depth", String(f.neo4j_depth || 1));
      formData.append("date_awareness_enabled", f.date_awareness_enabled ? "true" : "false");
      formData.append("include_company_rag", f.include_company_rag ? "true" : "false");
      formData.append("company_rag_folder_ids", JSON.stringify(f.company_rag_folder_ids || []));

      await api.put(`/agents/${currentAgent.id}`, formData, {
        headers: { "Content-Type": "multipart/form-data" }
      });
      setAutoSaveStatus('saved');
      // If photo was uploaded, reload to get new URL
      if (f.profile_photo) await loadAgentData(currentAgent.id);
      setTimeout(() => setAutoSaveStatus(s => s === 'saved' ? 'idle' : s), 2000);
    } catch {
      setAutoSaveStatus('error');
    }
  }, [currentAgent?.id, form, loadAgentData]);

  // Debounced auto-save: watches form changes
  useEffect(() => {
    if (!currentAgent?.id) return;
    // Skip the first render (initial form load from API)
    if (!formLoaded.current) {
      formLoaded.current = true;
      prevFormRef.current = JSON.stringify(form);
      return;
    }
    // Skip if form hasn't actually changed
    const formStr = JSON.stringify(form);
    if (formStr === prevFormRef.current) return;
    prevFormRef.current = formStr;

    // Immediate save for photo uploads
    if (form.profile_photo) {
      saveAgent(form);
      return;
    }

    // Debounced save for other changes
    if (autoSaveTimer.current) clearTimeout(autoSaveTimer.current);
    autoSaveTimer.current = setTimeout(() => saveAgent(form), 1500);
    return () => { if (autoSaveTimer.current) clearTimeout(autoSaveTimer.current); };
  }, [form, currentAgent?.id, saveAgent]);

  const improveContext = async () => {
    if (!form.contexte.trim()) {
      toast.error(t('agents:toast.noContextToImprove'));
      return;
    }
    setImprovingContext(true);
    try {
      const res = await api.post(`/api/agents/${currentAgent.id}/improve-context`, { contexte: form.contexte });
      setImprovedContext(res.data.improved);
      setShowImproveModal(true);
    } catch (error) {
      const detail = error.response?.data?.detail || error.response?.status || error.message;
      console.error("Improve context error:", error.response?.status, error.response?.data);
      toast.error(`${t('agents:toast.improveError')} (${detail})`);
    } finally {
      setImprovingContext(false);
    }
  };

  const acceptImprovedContext = () => {
    setForm(f => ({ ...f, contexte: improvedContext }));
    setShowImproveModal(false);
    setImprovedContext(null);
    toast.success(t('agents:toast.contextImproved'));
  };

  const pollUploadStatus = async (taskId, agentId, filename) => {
    const maxAttempts = 150; // ~3.75 min for large documents
    for (let i = 0; i < maxAttempts; i++) {
      await new Promise(r => setTimeout(r, 1500));
      try {
        const res = await api.get(`/upload-status/${taskId}`);
        const { status, error, progress, stage, total_chunks, current_chunk } = res.data;
        if (status === 'processing') {
          setUploadProgress({ progress: progress || 0, stage: stage || 'processing', filename, total_chunks, current_chunk });
        }
        if (status === 'completed') {
          setUploadProgress({ progress: 100, stage: 'done', filename });
          toast.success(t('agents:toast.documentAdded'));
          const docs = await api.get(`/user/documents?agent_id=${agentId}`);
          setAgentDocuments(docs.data.documents || []);
          loadAgentFolders(agentId);
          // Clear progress after a short delay so user sees 100%
          setTimeout(() => setUploadProgress(null), 1500);
          return;
        }
        if (status === 'failed') {
          setUploadProgress(null);
          toast.error(error || t('agents:toast.documentAddError'));
          return;
        }
      } catch { /* keep polling */ }
    }
    setUploadProgress(null);
    toast.error(t('agents:toast.documentAddError'));
  };

  const uploadDocument = async (file) => {
    setUploadingDoc(true);
    setUploadProgress({ progress: 0, stage: 'uploading', filename: file.name });
    try {
      const fd = new FormData();
      fd.append("file", file);
      fd.append("agent_id", currentAgent.id);
      if (uploadFolderId) {
        fd.append("folder_id", String(uploadFolderId));
      }
      const response = await api.post(`/upload-agent`, fd, {
        headers: { 'Content-Type': 'multipart/form-data' }
      });
      const data = response.data;
      if (data.status === 'processing' && data.task_id) {
        setUploadProgress({ progress: 5, stage: 'uploading', filename: file.name });
        await pollUploadStatus(data.task_id, currentAgent.id, file.name);
      } else {
        setUploadProgress({ progress: 100, stage: 'done', filename: file.name });
        toast.success(t('agents:toast.documentAdded'));
        await new Promise(r => setTimeout(r, 500));
        const res = await api.get(`/user/documents?agent_id=${currentAgent.id}`);
        setAgentDocuments(res.data.documents || []);
        loadAgentFolders(currentAgent.id);
        setTimeout(() => setUploadProgress(null), 1500);
      }
    } catch (error) {
      setUploadProgress(null);
      toast.error(error.response?.data?.detail || t('agents:toast.documentAddError'));
    } finally { setUploadingDoc(false); }
  };

  const ALLOWED_IMPORT_EXT = ['pdf', 'txt', 'docx', 'doc', 'json'];

  const pollImportStatus = async (taskId, agentId) => {
    for (let i = 0; i < 200; i++) {
      await new Promise(r => setTimeout(r, 1500));
      try {
        const res = await api.get(`/api/agents/${agentId}/folders/import-status/${taskId}`);
        const s = res.data;
        setImportProgress({ total: s.total, done: s.done, skipped: s.skipped, failed: s.failed });
        if (s.status === 'completed') {
          toast.success(t('agents:buttons.importDone', { done: s.done, skipped: s.skipped }));
          const docs = await api.get(`/user/documents?agent_id=${agentId}`);
          setAgentDocuments(docs.data.documents || []);
          loadAgentFolders(agentId);
          setTimeout(() => setImportProgress(null), 2000);
          return;
        }
        if (s.status === 'failed') {
          toast.error(s.error || t('agents:toast.documentAddError'));
          setImportProgress(null);
          return;
        }
      } catch { /* keep polling */ }
    }
    setImportProgress(null);
    toast.error(t('agents:toast.documentAddError'));
  };

  const handleFolderImport = async (e) => {
    const all = Array.from(e.target.files || []);
    e.target.value = '';
    if (!all.length || !currentAgent) return;
    const fd = new FormData();
    let count = 0;
    for (const file of all) {
      const rel = file.webkitRelativePath || file.name;
      const ext = rel.split('.').pop().toLowerCase();
      if (!ALLOWED_IMPORT_EXT.includes(ext)) continue;
      fd.append('files', file);
      fd.append('paths', rel);
      count++;
    }
    if (!count) { toast.error(t('agents:buttons.importNoSupported')); return; }
    if (uploadFolderId) fd.append('parent_id', String(uploadFolderId));
    try {
      setImportingFolder(true);
      setImportProgress({ total: count, done: 0, skipped: 0, failed: 0 });
      const res = await api.post(`/api/agents/${currentAgent.id}/folders/import`, fd, {
        headers: { 'Content-Type': 'multipart/form-data' },
      });
      if (res.data.import_task_id) {
        await pollImportStatus(res.data.import_task_id, currentAgent.id);
      } else {
        toast.success(t('agents:buttons.importDone', { done: res.data.done, skipped: res.data.skipped }));
        const docs = await api.get(`/user/documents?agent_id=${currentAgent.id}`);
        setAgentDocuments(docs.data.documents || []);
        loadAgentFolders(currentAgent.id);
        setImportProgress(null);
      }
    } catch (error) {
      toast.error(error.response?.data?.detail || t('agents:toast.documentAddError'));
      setImportProgress(null);
    } finally {
      setImportingFolder(false);
    }
  };

  // ---- Companion RAG folders (sections) ----
  const buildFolderTree = (flat) => {
    const byParent = {};
    flat.forEach((f) => {
      const key = f.parent_id ?? 'root';
      (byParent[key] = byParent[key] || []).push(f);
    });
    const make = (parentKey) =>
      (byParent[parentKey] || [])
        .sort((a, b) => a.name.localeCompare(b.name))
        .map((f) => ({ ...f, children: make(f.id) }));
    return make('root');
  };

  const folderOptions = () => {
    const out = [];
    const walk = (nodes, prefix) =>
      nodes.forEach((f) => {
        out.push({ id: f.id, label: prefix + f.name + (f.is_active ? '' : ' (inactif)') });
        walk(f.children, prefix + '— ');
      });
    walk(buildFolderTree(agentFolders), '');
    return out;
  };

  // Company-RAG folder selection (tree). A selected parent is expanded to its whole
  // subtree by the backend, so descendants of a selected folder are shown checked +
  // disabled (unchecking would be a no-op). To exclude a subfolder, uncheck the parent.
  const toggleCompanyRagFolder = (folderId) =>
    setForm(prev => {
      const base = (!prev.company_rag_folder_ids || prev.company_rag_folder_ids.length === 0)
        ? companyFolders.map(x => x.id)
        : [...prev.company_rag_folder_ids];
      const next = base.includes(folderId) ? base.filter(id => id !== folderId) : [...base, folderId];
      return { ...prev, company_rag_folder_ids: next.length === companyFolders.length ? [] : next };
    });

  const renderCompanyRagCheckboxes = (nodes, depth = 0, ancestorForcesInclude = false) =>
    nodes.map(f => {
      const all = !form.company_rag_folder_ids || form.company_rag_folder_ids.length === 0;
      const explicitlySelected = !all && form.company_rag_folder_ids.includes(f.id);
      const checked = all || explicitlySelected || ancestorForcesInclude;
      const disabled = ancestorForcesInclude;
      const childForces = ancestorForcesInclude || explicitlySelected;
      return (
        <div key={f.id} className="space-y-1.5">
          <div className="flex items-center" style={{ paddingLeft: depth * 16 }}>
            <label className={`flex items-center gap-2 px-3 py-1.5 rounded-button border text-sm ${disabled ? 'cursor-not-allowed opacity-70' : 'cursor-pointer'} ${checked ? 'bg-emerald-50 border-emerald-300 text-emerald-800' : 'bg-white border-gray-200 text-gray-600'}`}>
              <input type="checkbox" checked={checked} disabled={disabled} onChange={() => toggleCompanyRagFolder(f.id)} />
              {f.name}
              {disabled ? (
                <span className="text-xs text-gray-400">{t('agents:companyRagFolders.includedViaParent')}</span>
              ) : f.children.length > 0 ? (
                <span className="text-xs text-gray-400">{t('agents:companyRagFolders.includesSubfolders')}</span>
              ) : null}
            </label>
          </div>
          {f.children.length > 0 && renderCompanyRagCheckboxes(f.children, depth + 1, childForces)}
        </div>
      );
    });

  const handleCreateAgentFolder = async () => {
    const name = newFolderName.trim();
    if (!name || !currentAgent) return;
    try {
      await api.post(`/api/agents/${currentAgent.id}/folders`, { name, parent_id: createParentId });
      setNewFolderName('');
      if (createParentId) setCollapsedFolders((c) => ({ ...c, [createParentId]: false }));
      setCreateParentId(null);
      await loadAgentFolders(currentAgent.id);
    } catch (e) {
      toast.error(e?.response?.data?.detail || t('agents:folders.createError', 'Erreur lors de la création du dossier'));
    }
  };

  const handleRenameAgentFolder = async (folder) => {
    const name = (window.prompt(t('agents:folders.renamePrompt', 'Nouveau nom du dossier'), folder.name) || '').trim();
    if (!name || name === folder.name) return;
    try {
      await api.put(`/api/agents/${currentAgent.id}/folders/${folder.id}`, { name });
      await loadAgentFolders(currentAgent.id);
    } catch (e) {
      toast.error(e?.response?.data?.detail || t('agents:folders.renameError', 'Erreur lors du renommage'));
    }
  };

  const handleToggleAgentFolder = async (folder) => {
    try {
      await api.put(`/api/agents/${currentAgent.id}/folders/${folder.id}`, { is_active: !folder.is_active });
      await loadAgentFolders(currentAgent.id);
    } catch (e) {
      toast.error(e?.response?.data?.detail || t('agents:folders.toggleError', 'Erreur'));
    }
  };

  const handleDeleteAgentFolder = async (folder) => {
    if (!confirm(t('agents:folders.deleteConfirm', 'Supprimer ce dossier ? (il doit être vide)'))) return;
    try {
      await api.delete(`/api/agents/${currentAgent.id}/folders/${folder.id}`);
      if (selectedFolderId === folder.id) setSelectedFolderId(null);
      await loadAgentFolders(currentAgent.id);
    } catch (e) {
      toast.error(e?.response?.data?.detail || t('agents:folders.deleteError', 'Impossible de supprimer (non vide ?)'));
    }
  };

  const handleMoveAgentDoc = async (docId, targetFolderId) => {
    try {
      await api.put(`/api/agents/${currentAgent.id}/documents/${docId}/folder`, {
        folder_id: targetFolderId === '' ? null : Number(targetFolderId),
      });
      const docs = await api.get(`/user/documents?agent_id=${currentAgent.id}`);
      setAgentDocuments(docs.data.documents || []);
      loadAgentFolders(currentAgent.id);
    } catch (e) {
      toast.error(e?.response?.data?.detail || t('agents:folders.moveError', 'Impossible de déplacer le document'));
    }
  };

  const renderAgentFolderNodes = (nodes, depth = 0) =>
    nodes.map((f) => (
      <div key={f.id}>
        <div className="flex items-center gap-1" style={{ paddingLeft: depth * 16 }}>
          {f.children.length > 0 ? (
            <button type="button"
              onClick={() => setCollapsedFolders((c) => ({ ...c, [f.id]: !c[f.id] }))}
              className="w-4 text-gray-400 hover:text-gray-700"
              title={collapsedFolders[f.id] ? t('agents:folders.expand', 'Déplier') : t('agents:folders.collapse', 'Replier')}>
              {collapsedFolders[f.id] ? '▸' : '▾'}
            </button>
          ) : (
            <span className="w-4" />
          )}
          <div
            onClick={() => setSelectedFolderId(f.id)}
            className={`group flex items-center rounded-button border px-3 py-1.5 text-sm cursor-pointer transition-colors ${selectedFolderId === f.id ? 'bg-purple-50 border-purple-300 text-purple-700' : 'bg-white border-gray-200 text-gray-600 hover:bg-gray-50'} ${!f.is_active ? 'opacity-50' : ''}`}>
            <span className="font-medium">{f.name}</span>
            <span className="ml-2 text-xs text-gray-400">{f.document_count}</span>
            <span className="ml-2 hidden group-hover:inline-flex items-center gap-1.5">
              <button type="button" title={t('agents:folders.addSubfolder', 'Sous-dossier')}
                onClick={(ev) => { ev.stopPropagation(); setCreateParentId(f.id); }}
                className="text-gray-400 hover:text-gray-700"><Plus className="w-3.5 h-3.5" /></button>
              <button type="button" title={f.is_active ? t('agents:folders.deactivate', 'Désactiver') : t('agents:folders.activate', 'Activer')}
                onClick={(ev) => { ev.stopPropagation(); handleToggleAgentFolder(f); }}
                className="text-gray-400 hover:text-gray-700">{f.is_active ? <Eye className="w-3.5 h-3.5" /> : <EyeOff className="w-3.5 h-3.5" />}</button>
              <button type="button" title={t('agents:folders.rename', 'Renommer')}
                onClick={(ev) => { ev.stopPropagation(); handleRenameAgentFolder(f); }}
                className="text-gray-400 hover:text-gray-700"><Pencil className="w-3.5 h-3.5" /></button>
              <button type="button" title={t('agents:folders.delete', 'Supprimer')}
                onClick={(ev) => { ev.stopPropagation(); handleDeleteAgentFolder(f); }}
                className="text-red-400 hover:text-red-600"><Trash2 className="w-3.5 h-3.5" /></button>
            </span>
          </div>
        </div>
        {!collapsedFolders[f.id] && f.children.length > 0 && (
          <div className="mt-2 space-y-2">{renderAgentFolderNodes(f.children, depth + 1)}</div>
        )}
      </div>
    ));

  const deleteDocument = async (docId) => {
    if (!confirm(t('agents:toast.documentDeleteConfirm'))) return;
    try {
      await api.delete(`/documents/${docId}`);
      toast.success(t('agents:toast.documentDeleted'));
      setAgentDocuments(prev => prev.filter(d => d.id !== docId));
    } catch { toast.error(t('agents:toast.deleteError')); }
  };

  const handleAddUrl = async () => {
    if (!urlInput.trim() || !currentAgent) return;
    setAddingUrl(true);
    try {
      await api.post("/upload-url", { url: urlInput.trim(), agent_id: currentAgent.id });
      toast.success(t('agents:toast.urlAddSuccess'));
      setUrlInput("");
      const res = await api.get(`/user/documents?agent_id=${currentAgent.id}`);
      setAgentDocuments(res.data.documents || []);
    } catch (error) {
      toast.error(error.response?.data?.detail || t('agents:toast.urlAddError'));
    } finally { setAddingUrl(false); }
  };

  const handleRefreshUrl = async (docId) => {
    setRefreshingDocId(docId);
    try {
      await api.post(`/documents/${docId}/refresh-url`);
      toast.success(t('agents:toast.urlRefreshSuccess'));
      const res = await api.get(`/user/documents?agent_id=${currentAgent.id}`);
      setAgentDocuments(res.data.documents || []);
    } catch (error) {
      toast.error(error.response?.data?.detail || t('agents:toast.urlRefreshError'));
    } finally { setRefreshingDocId(null); }
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

  const addDriveLink = async () => {
    if (!driveInput.trim()) return;
    setAddingDriveLink(true);
    try {
      await api.post(`/api/agents/${currentAgent.id}/drive-links`, { url: driveInput });
      toast.success(t('agents:toast.driveLinkAdded'));
      setDriveInput("");
      await loadDriveLinks(currentAgent.id);
    } catch (error) {
      toast.error(error.response?.data?.detail || t('agents:toast.driveLinkError'));
    } finally { setAddingDriveLink(false); }
  };

  const deleteDriveLink = async (linkId) => {
    try {
      await api.delete(`/api/agents/${currentAgent.id}/drive-links/${linkId}`);
      toast.success(t('agents:toast.driveLinkDeleted'));
      await Promise.all([loadDriveLinks(currentAgent.id), refreshAgentDocuments()]);
    } catch { toast.error(t('agents:toast.deleteError')); }
  };

  const ingestDriveLink = async (linkId) => {
    setSyncingDriveLinkId(linkId);
    try {
      const res = await api.post(`/api/agents/${currentAgent.id}/drive-links/${linkId}/ingest`, {});
      toast.success(t('agents:toast.driveIngestSuccess', { files: res.data.files_processed, chunks: res.data.chunk_count }));
      await Promise.all([loadDriveLinks(currentAgent.id), refreshAgentDocuments()]);
    } catch (error) {
      toast.error(error.response?.data?.detail || t('agents:toast.driveIngestError'));
    } finally { setSyncingDriveLinkId(null); }
  };

  const resyncDriveLink = async (linkId) => {
    setSyncingDriveLinkId(linkId);
    try {
      const res = await api.post(`/api/agents/${currentAgent.id}/drive-links/${linkId}/resync`, {});
      toast.success(t('agents:toast.driveResyncSuccess', { files: res.data.new_files_added, chunks: res.data.chunk_count }));
      await Promise.all([loadDriveLinks(currentAgent.id), refreshAgentDocuments()]);
    } catch (error) {
      toast.error(error.response?.data?.detail || t('agents:toast.driveResyncError'));
    } finally { setSyncingDriveLinkId(null); }
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
      if (['.pdf', '.txt', '.doc', '.docx', '.json'].includes(ext)) uploadDocument(file);
      else toast.error(t('agents:toast.unsupportedFormat'));
    } else {
      if (['.pdf', '.txt', '.docx', '.xlsx', '.xls', '.csv', '.json'].includes(ext)) uploadTraceabilityDoc(file);
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
          <Loader2 className="w-12 h-12 text-primary-600 animate-spin mx-auto mb-4" />
          <p className="text-gray-500 font-medium">{t('agents:loading')}</p>
        </div>
      </div>
    );
  }

  const typeConfig = AGENT_TYPES[currentAgent.type] || AGENT_TYPES.conversationnel;
  const apiUrl = '/_api';
  const profilePhotoUrl = form.profile_photo
    ? URL.createObjectURL(form.profile_photo)
    : currentAgent.profile_photo
      ? `${apiUrl}/api/agent-photo/${currentAgent.id}`
      : null;

  return (
    <Layout
      title={currentAgent?.name || ''}
      onLogout={logout}
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
                    className="w-32 h-32 rounded-card object-cover border-4 border-white shadow-elevated ring-4 ring-primary-100"
                    onError={e => { e.target.onerror = null; e.target.src = '/default-avatar.svg'; }}
                  />
                ) : (
                  <div className={`w-32 h-32 rounded-card ${typeConfig.color} flex items-center justify-center border-4 border-white shadow-elevated ring-4 ring-primary-100`}>
                    <Bot className="w-16 h-16 text-white" />
                  </div>
                )}
                <label className="absolute inset-0 rounded-card bg-black/40 opacity-0 group-hover:opacity-100 transition-opacity cursor-pointer flex items-center justify-center">
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
                <div className="group/name relative flex items-center gap-2">
                  <input
                    type="text"
                    value={form.name}
                    onChange={e => setForm(f => ({ ...f, name: e.target.value }))}
                    className="text-3xl font-bold text-gray-900 bg-transparent border-b-2 border-transparent hover:border-gray-300 focus:border-primary-500 outline-none w-full placeholder-gray-300 transition-colors duration-200"
                    placeholder={t('agents:form.name.placeholder')}
                  />
                  <Pencil className="w-5 h-5 text-gray-400 opacity-0 group-hover/name:opacity-100 transition-opacity duration-200 flex-shrink-0 pointer-events-none" />
                </div>
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
                  {form.date_awareness_enabled && (
                    <span className="inline-flex items-center px-3 py-1 bg-indigo-500 text-white text-xs font-semibold rounded-full shadow-sm">
                      <Calendar className="w-3 h-3 mr-1" /> Date
                    </span>
                  )}
                  {form.weekly_recap_enabled && (
                    <span className="inline-flex items-center px-3 py-1 bg-amber-500 text-white text-xs font-semibold rounded-full shadow-sm">
                      <Mail className="w-3 h-3 mr-1" /> Recap
                    </span>
                  )}
                </div>
              </div>

              {/* Chat button + auto-save indicator - desktop */}
              <div className="hidden sm:flex items-center gap-3 flex-shrink-0">
                {autoSaveStatus === 'saving' && (
                  <span className="flex items-center gap-1.5 text-sm text-gray-400 animate-pulse">
                    <Loader2 className="w-4 h-4 animate-spin" />
                    {t('agents:autosave.saving')}
                  </span>
                )}
                {autoSaveStatus === 'saved' && (
                  <span className="flex items-center gap-1.5 text-sm text-green-600">
                    <Check className="w-4 h-4" />
                    {t('agents:autosave.saved')}
                  </span>
                )}
                {autoSaveStatus === 'error' && (
                  <span className="flex items-center gap-1.5 text-sm text-red-500 cursor-pointer" onClick={() => saveAgent()}>
                    <AlertCircle className="w-4 h-4" />
                    {t('agents:autosave.error')}
                  </span>
                )}
                <button
                  onClick={() => router.push(`/chat/${currentAgent.id}`)}
                  className="flex items-center space-x-2 px-6 py-3 bg-gradient-to-r from-blue-600 to-purple-600 hover:from-blue-700 hover:to-purple-700 text-white rounded-button font-semibold shadow-card hover:shadow-elevated transition-all"
                >
                  <MessageCircle className="w-5 h-5" />
                  <span>{t('agents:buttons.openChat')}</span>
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
                className="w-full px-4 py-3 border border-gray-200 rounded-input focus:border-primary-500 focus:ring-2 focus:ring-primary-100 transition-all outline-none bg-white resize-y"
                rows="4"
                value={form.contexte}
                onChange={e => setForm(f => ({ ...f, contexte: e.target.value }))}
              />
              <button
                type="button"
                onClick={improveContext}
                disabled={improvingContext || !form.contexte.trim()}
                className="mt-2 inline-flex items-center gap-2 px-4 py-2 bg-gradient-to-r from-amber-500 to-orange-500 hover:from-amber-600 hover:to-orange-600 text-white text-sm font-semibold rounded-button shadow-sm hover:shadow-card transition-all disabled:opacity-50 disabled:cursor-not-allowed"
              >
                {improvingContext ? (
                  <Loader2 className="w-4 h-4 animate-spin" />
                ) : (
                  <Sparkles className="w-4 h-4" />
                )}
                {improvingContext
                  ? t('agents:buttons.improving')
                  : t('agents:buttons.improveContext')
                }
              </button>
            </div>
            <div>
              <label className="text-sm font-semibold text-gray-700 mb-1 block">{t('agents:form.biography.placeholder')}</label>
              <textarea
                className="w-full px-4 py-3 border border-gray-200 rounded-input focus:border-primary-500 focus:ring-2 focus:ring-primary-100 transition-all outline-none bg-white resize-y"
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

          {/* Plugin selector for actionnable agents */}
          {form.type === 'actionnable' && (
            <div className="mt-4">
              <PluginSelector
                enabledPlugins={form.enabled_plugins}
                onChange={(plugins) => setForm(f => ({ ...f, enabled_plugins: plugins }))}
              />
            </div>
          )}

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
                className="px-4 py-2 bg-purple-600 text-white rounded-button hover:bg-purple-700 transition-colors text-sm font-medium"
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
            <div className="flex items-center justify-between mb-4 p-3 bg-teal-50 rounded-button border border-teal-200">
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
              <div className="space-y-4">
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
              {/* Graph Ingest Section */}
              <div className="pt-4 mt-4 border-t border-teal-200">
                <label className="text-sm font-medium text-gray-600 mb-2 block">{t('agents:form.neo4j.ingestLabel')}</label>
                <input
                  type="text"
                  placeholder={t('agents:form.neo4j.ingestSourcePlaceholder')}
                  className="w-full px-3 py-2.5 mb-2 border border-teal-200 rounded-input focus:border-teal-500 focus:ring-2 focus:ring-teal-200 transition-all outline-none bg-white text-sm"
                  value={graphIngestSource}
                  onChange={e => setGraphIngestSource(e.target.value)}
                />
                <textarea
                  placeholder={t('agents:form.neo4j.ingestPlaceholder')}
                  className="w-full px-3 py-2.5 border border-teal-200 rounded-input focus:border-teal-500 focus:ring-2 focus:ring-teal-200 transition-all outline-none bg-white text-sm resize-y"
                  rows={4}
                  value={graphIngestText}
                  onChange={e => setGraphIngestText(e.target.value)}
                />
                <button
                  type="button"
                  disabled={graphIngesting || !graphIngestText.trim() || !graphIngestSource.trim()}
                  onClick={handleGraphIngest}
                  className="mt-2 px-4 py-2.5 bg-teal-600 text-white rounded-button hover:bg-teal-700 transition-colors text-sm font-medium disabled:opacity-50 disabled:cursor-not-allowed flex items-center"
                >
                  {graphIngesting ? (
                    <>
                      <Loader2 className="animate-spin w-4 h-4 mr-2" />
                      {t('agents:form.neo4j.ingesting')}
                    </>
                  ) : (
                    <>
                      <Send className="w-4 h-4 mr-2" />
                      {t('agents:form.neo4j.ingestButton')}
                    </>
                  )}
                </button>
                {/* File upload separator */}
                <div className="flex items-center gap-3 mt-4 mb-2">
                  <div className="flex-1 border-t border-teal-200" />
                  <span className="text-xs text-gray-400 uppercase font-medium">{t('agents:form.neo4j.ingestFileOr')}</span>
                  <div className="flex-1 border-t border-teal-200" />
                </div>
                <input
                  ref={graphFileInputRef}
                  type="file"
                  accept=".pdf,.txt,.docx"
                  className="hidden"
                  onChange={handleGraphFileUpload}
                />
                <button
                  type="button"
                  disabled={graphFileUploading}
                  onClick={() => graphFileInputRef.current?.click()}
                  className="px-4 py-2.5 bg-teal-50 text-teal-700 border border-teal-300 rounded-button hover:bg-teal-100 transition-colors text-sm font-medium disabled:opacity-50 disabled:cursor-not-allowed flex items-center"
                >
                  {graphFileUploading ? (
                    <>
                      <Loader2 className="animate-spin w-4 h-4 mr-2" />
                      {t('agents:form.neo4j.ingestFileUploading')}
                    </>
                  ) : (
                    <>
                      <Upload className="w-4 h-4 mr-2" />
                      {t('agents:form.neo4j.ingestFileButton')}
                    </>
                  )}
                </button>
                <p className="text-xs text-gray-400 mt-1">{t('agents:form.neo4j.ingestFileAccept')}</p>
              </div>
              </div>
            )}
          </Section>
        )}

        {/* Date Awareness */}
        <Section
          icon={Calendar}
          title={t('agents:form.dateAwareness.label')}
          subtitle={t('agents:form.dateAwareness.helpText')}
          color="bg-indigo-500"
        >
          <div className="flex items-center justify-between p-3 bg-indigo-50 rounded-button border border-indigo-200">
            <span className="text-sm font-semibold text-gray-700">{t('agents:form.dateAwareness.label')}</span>
            <button
              type="button"
              className={`w-14 h-7 flex items-center rounded-full px-1 transition-colors duration-200 focus:outline-none border-2 ${form.date_awareness_enabled ? 'bg-indigo-500 border-indigo-500' : 'bg-gray-200 border-gray-300'}`}
              onClick={() => setForm(f => ({ ...f, date_awareness_enabled: !f.date_awareness_enabled }))}
            >
              <span className={`h-5 w-5 rounded-full shadow transition-transform duration-200 ${form.date_awareness_enabled ? 'bg-white translate-x-7' : 'bg-gray-400 translate-x-0'}`} />
            </button>
          </div>
        </Section>

        {/* Company RAG */}
        <Section
          icon={FileText}
          title={t('agents:companyRag.label')}
          subtitle={t('agents:companyRag.help')}
          color="bg-emerald-600"
        >
          <div className="flex items-center justify-between p-3 bg-emerald-50 rounded-button border border-emerald-200">
            <span className="text-sm font-semibold text-gray-700">{t('agents:companyRag.label')}</span>
            <button
              type="button"
              className={`w-14 h-7 flex items-center rounded-full px-1 transition-colors duration-200 focus:outline-none border-2 ${form.include_company_rag ? 'bg-emerald-600 border-emerald-600' : 'bg-gray-200 border-gray-300'}`}
              onClick={() => setForm(f => ({ ...f, include_company_rag: !f.include_company_rag }))}
            >
              <span className={`h-5 w-5 rounded-full shadow transition-transform duration-200 ${form.include_company_rag ? 'bg-white translate-x-7' : 'bg-gray-400 translate-x-0'}`} />
            </button>
          </div>
          {form.include_company_rag && companyFolders.length > 0 && (
            <div className="mt-3 ml-1 space-y-2">
              <p className="text-xs text-gray-500">{t('agents:companyRagFolders.label')}</p>
              <div className="space-y-1.5">
                {renderCompanyRagCheckboxes(buildFolderTree(companyFolders))}
              </div>
              <p className="text-xs text-gray-400">{t('agents:companyRagFolders.allHint')}</p>
            </div>
          )}
        </Section>

        {/* RAG Documents */}
        <Section
          icon={FileText}
          title={t('agents:documents.title', { count: agentDocuments.length })}
          subtitle={t('agents:settings.ragDocsDesc')}
          color="bg-purple-500"
        >
          {/* Drop zone */}
          <div
            className={`relative border-2 border-dashed rounded-button p-8 mb-4 transition-all duration-300 text-center ${
              isDragging ? 'border-purple-500 bg-purple-50 scale-[1.01]' : 'border-gray-300 bg-gradient-to-br from-gray-50 to-purple-50/50 hover:border-purple-400'
            }`}
            onDragOver={e => { e.preventDefault(); e.stopPropagation(); setIsDragging(true); }}
            onDragEnter={e => { e.preventDefault(); e.stopPropagation(); setIsDragging(true); }}
            onDragLeave={e => { e.preventDefault(); e.stopPropagation(); setIsDragging(false); }}
            onDrop={e => handleFileDrop(e, 'rag')}
          >
            {uploadProgress ? (
              /* Progress bar during upload */
              <div className="py-2">
                <div className="flex items-center justify-center gap-2 mb-3">
                  <Loader2 className="w-5 h-5 text-purple-600 animate-spin" />
                  <span className="font-semibold text-gray-700 text-sm">{uploadProgress.filename}</span>
                </div>
                <div className="w-full max-w-md mx-auto bg-gray-200 rounded-full h-3 mb-2 overflow-hidden">
                  <div
                    className="h-full rounded-full bg-gradient-to-r from-purple-500 to-blue-500 transition-all duration-500 ease-out"
                    style={{ width: `${Math.max(uploadProgress.progress, 2)}%` }}
                  />
                </div>
                <div className="flex items-center justify-between max-w-md mx-auto">
                  <span className="text-xs text-gray-500">
                    {uploadProgress.stage === 'uploading' && t('agents:upload.stageUploading')}
                    {uploadProgress.stage === 'extracting' && (
                      uploadProgress.current_chunk && uploadProgress.total_chunks
                        ? t('agents:upload.stageExtractingPages', { current: uploadProgress.current_chunk, total: uploadProgress.total_chunks })
                        : t('agents:upload.stageExtracting')
                    )}
                    {uploadProgress.stage === 'extracted' && t('agents:upload.stageExtracted')}
                    {uploadProgress.stage === 'chunking' && t('agents:upload.stageChunking', { count: uploadProgress.total_chunks || '...' })}
                    {uploadProgress.stage === 'embedding' && t('agents:upload.stageEmbedding', { current: uploadProgress.current_chunk || 0, total: uploadProgress.total_chunks || '...' })}
                    {uploadProgress.stage === 'done' && t('agents:upload.stageDone')}
                    {uploadProgress.stage === 'starting' && t('agents:upload.stageStarting')}
                    {uploadProgress.stage === 'processing' && t('agents:upload.stageProcessing')}
                  </span>
                  <span className="text-xs font-semibold text-purple-600">{uploadProgress.progress}%</span>
                </div>
              </div>
            ) : (
              /* Normal drop zone */
              <>
                <div className={`p-4 rounded-full inline-flex mb-3 transition-all ${isDragging ? 'bg-purple-200 scale-110' : 'bg-purple-100'}`}>
                  <Upload className={`w-8 h-8 ${isDragging ? 'text-purple-700' : 'text-purple-500'}`} />
                </div>
                <p className="font-semibold text-gray-700 mb-1">
                  {isDragging ? t('agents:documents.dropHere') : t('agents:documents.dragDrop')}
                </p>
                <p className="text-xs text-gray-500 mb-3">{t('agents:documents.formats')}</p>
                <div className="inline-flex items-center gap-2">
                  <label className="cursor-pointer inline-flex items-center space-x-2 px-4 py-2 bg-gradient-to-r from-purple-600 to-blue-600 text-white rounded-sm hover:from-purple-700 hover:to-blue-700 transition-all font-medium text-sm shadow-card hover:shadow-elevated">
                    <input type="file" className="hidden" accept=".pdf,.txt,.doc,.docx,.json" disabled={uploadingDoc}
                      onChange={e => { if (e.target.files?.[0]) { uploadDocument(e.target.files[0]); e.target.value = ''; } }} />
                    <Plus className="w-4 h-4" /><span>{t('agents:buttons.clickToChoose')}</span>
                  </label>
                  <label className={`cursor-pointer inline-flex items-center space-x-2 px-4 py-2 bg-white border border-purple-300 text-purple-700 rounded-sm hover:bg-purple-50 transition-all font-medium text-sm ${importingFolder ? 'opacity-60 pointer-events-none' : ''}`}>
                    <input ref={setFolderInputRef} type="file" multiple className="hidden" disabled={importingFolder}
                      onChange={handleFolderImport} />
                    {importingFolder ? <Loader2 className="w-4 h-4 animate-spin" /> : <Upload className="w-4 h-4" />}
                    <span>{importingFolder ? t('agents:buttons.importingFolder') : t('agents:buttons.importFolder')}</span>
                  </label>
                </div>
                {importProgress && (
                  <div className="mt-3 text-xs text-gray-600 max-w-xs mx-auto">
                    <div className="h-2 bg-gray-200 rounded-full overflow-hidden">
                      <div className="h-full bg-purple-600 transition-all"
                        style={{ width: `${importProgress.total ? Math.round(((importProgress.done + importProgress.skipped + importProgress.failed) / importProgress.total) * 100) : 0}%` }} />
                    </div>
                    <span>{importProgress.done + importProgress.skipped + importProgress.failed}/{importProgress.total} · {t('agents:buttons.importDone', { done: importProgress.done, skipped: importProgress.skipped })}</span>
                  </div>
                )}
                {agentFolders.length > 0 && (
                  <div className="mt-3">
                    <select
                      value={uploadFolderId ?? ''}
                      onChange={e => setUploadFolderId(e.target.value === '' ? null : Number(e.target.value))}
                      className="px-3 py-2 border border-gray-200 rounded-sm text-sm focus:border-purple-500 focus:ring-2 focus:ring-purple-200 outline-none transition-all bg-white"
                      title={t('agents:folders.uploadTarget', 'Dossier de destination')}
                    >
                      <option value="">{t('agents:folders.noFolder', 'Sans dossier')}</option>
                      {folderOptions().map(o => (
                        <option key={o.id} value={o.id}>{o.label}</option>
                      ))}
                    </select>
                  </div>
                )}
              </>
            )}
          </div>

          {/* URL input */}
          <div className="flex items-center gap-2 mb-4">
            <Globe className="w-5 h-5 text-purple-500 flex-shrink-0" />
            <input
              type="url"
              className="flex-1 px-3 py-2 border border-gray-200 rounded-sm text-sm focus:border-purple-500 focus:ring-2 focus:ring-purple-200 outline-none transition-all"
              placeholder={t('agents:url.placeholder', 'https://example.com/page')}
              value={urlInput}
              onChange={e => setUrlInput(e.target.value)}
              onKeyDown={e => { if (e.key === 'Enter') handleAddUrl(); }}
            />
            <button
              onClick={handleAddUrl}
              disabled={addingUrl || !urlInput.trim()}
              className="px-4 py-2 bg-gradient-to-r from-purple-600 to-blue-600 text-white rounded-sm hover:from-purple-700 hover:to-blue-700 transition-all font-medium text-sm disabled:opacity-50 disabled:cursor-not-allowed flex items-center gap-1.5"
            >
              {addingUrl ? <><Loader2 className="w-4 h-4 animate-spin" /><span>{t('agents:url.adding', 'Ajout...')}</span></> : <><Plus className="w-4 h-4" /><span>{t('agents:url.add', 'Ajouter URL')}</span></>}
            </button>
          </div>

          {/* Folder tree (sections) */}
          <div className="mb-4">
            <div className="space-y-2">
              <button
                type="button"
                onClick={() => setSelectedFolderId(null)}
                className={`px-3 py-1.5 rounded-button border text-sm transition-colors ${selectedFolderId === null ? 'bg-purple-50 border-purple-300 text-purple-700' : 'bg-white border-gray-200 text-gray-600 hover:bg-gray-50'}`}
              >
                {t('agents:folders.all', 'Tous les documents')}
              </button>
              {renderAgentFolderNodes(buildFolderTree(agentFolders))}
            </div>
            <div className="mt-3">
              {createParentId !== null && (
                <div className="mb-2 flex items-center gap-2 text-xs text-gray-500">
                  <span>
                    {t('agents:folders.newSubfolderIn', 'Nouveau sous-dossier dans :')}{' '}
                    <span className="font-medium text-gray-700">{agentFolders.find(f => f.id === createParentId)?.name || ''}</span>
                  </span>
                  <button type="button" onClick={() => setCreateParentId(null)} className="text-gray-400 hover:text-gray-700 underline">
                    {t('common:cancel', 'Annuler')}
                  </button>
                </div>
              )}
              <div className="flex items-center gap-2">
                <input
                  type="text"
                  value={newFolderName}
                  onChange={e => setNewFolderName(e.target.value)}
                  onKeyDown={e => { if (e.key === 'Enter') { e.preventDefault(); handleCreateAgentFolder(); } }}
                  placeholder={createParentId !== null ? t('agents:folders.newSubfolderPlaceholder', 'Nouveau sous-dossier') : t('agents:folders.newPlaceholder', 'Nouveau dossier')}
                  className="px-3 py-1.5 border border-gray-200 rounded-sm text-sm focus:border-purple-500 focus:ring-2 focus:ring-purple-200 outline-none transition-all"
                />
                <button
                  type="button"
                  onClick={handleCreateAgentFolder}
                  disabled={!newFolderName.trim()}
                  className="flex items-center gap-1 px-3 py-1.5 bg-purple-600 hover:bg-purple-700 disabled:bg-gray-300 text-white text-sm font-medium rounded-sm transition-colors"
                >
                  <Plus className="w-4 h-4" /><span>{t('agents:folders.create', 'Créer')}</span>
                </button>
              </div>
            </div>
          </div>

          {/* Documents list */}
          <div className="space-y-2 max-h-64 overflow-y-auto">
            {(selectedFolderId === null ? agentDocuments : agentDocuments.filter(d => d.agent_folder_id === selectedFolderId)).length === 0 ? (
              <div className="text-center py-6 text-gray-400">
                <FileText className="w-10 h-10 mx-auto mb-2 opacity-50" />
                <p className="text-sm">{t('agents:documents.noDocuments')}</p>
              </div>
            ) : (selectedFolderId === null ? agentDocuments : agentDocuments.filter(d => d.agent_folder_id === selectedFolderId)).map(doc => (
              <div key={doc.id} className="flex items-center justify-between p-3 bg-white rounded-button border border-gray-200 hover:border-purple-300 transition-all group">
                <div className="flex items-center space-x-3 flex-1 min-w-0">
                  {doc.source_url ? <Globe className="w-5 h-5 text-primary-600 flex-shrink-0" /> : <FileText className="w-5 h-5 text-purple-600 flex-shrink-0" />}
                  <div className="flex-1 min-w-0">
                    <p className="text-sm font-medium text-gray-900 truncate">{doc.filename}</p>
                    <p className="text-xs text-gray-500">{new Date(doc.created_at).toLocaleDateString('fr-FR')}</p>
                  </div>
                  {doc.source_url && (
                    <span className="px-2 py-0.5 text-xs rounded-full bg-primary-50 text-primary-600 border border-primary-100 flex-shrink-0">URL</span>
                  )}
                  {doc.notion_link_id && (
                    <span className="px-2 py-0.5 text-xs rounded-full bg-primary-50 text-primary-600 border border-primary-100 flex-shrink-0">Notion</span>
                  )}
                  {doc.drive_link_id && (
                    <span className="px-2 py-0.5 text-xs rounded-full bg-emerald-50 text-emerald-600 border border-emerald-200 flex-shrink-0">Drive</span>
                  )}
                </div>
                <div className="flex items-center space-x-1">
                  {agentFolders.length > 0 && (
                    <select
                      value={doc.agent_folder_id ?? ''}
                      onChange={e => handleMoveAgentDoc(doc.id, e.target.value)}
                      onClick={e => e.stopPropagation()}
                      className="text-xs border border-gray-200 rounded-sm px-2 py-1 bg-white text-gray-600 opacity-0 group-hover:opacity-100"
                      title={t('agents:folders.moveTo', 'Déplacer vers')}
                      aria-label={t('agents:folders.moveTo', 'Déplacer vers')}
                    >
                      <option value="">{t('agents:folders.noFolder', 'Sans dossier')}</option>
                      {folderOptions().map(o => (
                        <option key={o.id} value={o.id}>{o.label}</option>
                      ))}
                    </select>
                  )}
                  {doc.source_url && (
                    <button
                      onClick={() => handleRefreshUrl(doc.id)}
                      disabled={refreshingDocId === doc.id}
                      className="p-2 text-gray-400 hover:text-primary-600 hover:bg-primary-50 rounded-sm transition-all opacity-0 group-hover:opacity-100 disabled:opacity-100"
                      title={t('agents:url.refresh')}
                    >
                      {refreshingDocId === doc.id ? <Loader2 className="w-4 h-4 animate-spin text-primary-500" /> : <RefreshCw className="w-4 h-4" />}
                    </button>
                  )}
                  {doc.notion_link_id && (
                    <button
                      onClick={() => resyncNotionDoc(doc)}
                      disabled={resyncingDocId === doc.id}
                      className="p-2 text-gray-400 hover:text-primary-600 hover:bg-primary-50 rounded-sm transition-all opacity-0 group-hover:opacity-100 disabled:opacity-100"
                      title={t('agents:buttons.resyncNotion')}
                    >
                      {resyncingDocId === doc.id ? <Loader2 className="w-4 h-4 animate-spin text-primary-500" /> : <RefreshCw className="w-4 h-4" />}
                    </button>
                  )}
                  <button onClick={() => deleteDocument(doc.id)} className="p-2 text-gray-400 hover:text-red-600 hover:bg-red-50 rounded-sm transition-all opacity-0 group-hover:opacity-100" title={t('agents:buttons.delete')}>
                    <Trash2 className="w-4 h-4" />
                  </button>
                </div>
              </div>
            ))}
          </div>
        </Section>

        {/* Recaps */}
        <Section
          icon={Mail}
          title={`Recaps (${recaps.length})`}
          subtitle="Gérez vos recaps et leurs documents de traçabilité"
          color="bg-amber-500"
          defaultOpen={false}
        >
          <div>
            <div className="flex items-center justify-between mb-3">
              <p className="text-sm font-semibold text-gray-700 flex items-center">
                <Mail className="w-4 h-4 mr-2 text-amber-600" />
                Recaps
              </p>
              <button
                type="button"
                onClick={() => setShowRecapCreate(true)}
                className="flex items-center gap-1 px-3 py-1.5 bg-amber-500 hover:bg-amber-600 text-white text-xs font-medium rounded-sm transition-colors"
              >
                <Plus className="w-3.5 h-3.5" /> Nouveau recap
              </button>
            </div>

            {/* Create Form */}
            {showRecapCreate && (
              <div className="mb-3 p-3 bg-white rounded-sm border border-amber-200">
                <input
                  type="text"
                  className="w-full px-3 py-2 border border-amber-200 rounded-sm text-sm mb-2"
                  placeholder="Nom du recap..."
                  value={recapForm.name}
                  onChange={e => setRecapForm(f => ({ ...f, name: e.target.value }))}
                />
                <div className="grid grid-cols-2 gap-2 mb-2">
                  <select
                    className="px-3 py-2 border border-amber-200 rounded-sm text-sm bg-white"
                    value={recapForm.frequency}
                    onChange={e => setRecapForm(f => ({ ...f, frequency: e.target.value }))}
                  >
                    {["daily", "weekly", "monthly"].map(freq => (
                      <option key={freq} value={freq}>
                        {t(`agents:form.weeklyRecap.frequencyOptions.${freq}`)}
                      </option>
                    ))}
                  </select>
                  <select
                    className="px-3 py-2 border border-amber-200 rounded-sm text-sm bg-white"
                    value={recapForm.hour}
                    onChange={e => setRecapForm(f => ({ ...f, hour: parseInt(e.target.value, 10) }))}
                  >
                    {Array.from({ length: 24 }, (_, i) => (
                      <option key={i} value={i}>{i}h</option>
                    ))}
                  </select>
                </div>
                <div className="flex gap-2">
                  <button
                    type="button"
                    onClick={createRecap}
                    disabled={savingRecap || !recapForm.name.trim()}
                    className="px-4 py-1.5 bg-amber-500 hover:bg-amber-600 disabled:bg-amber-300 text-white text-sm rounded-sm transition-colors"
                  >
                    {savingRecap ? 'Création...' : 'Créer'}
                  </button>
                  <button
                    type="button"
                    onClick={() => { setShowRecapCreate(false); setRecapForm({ name: '', enabled: true, frequency: 'weekly', hour: 9, prompt: '', recipients: [] }); }}
                    className="px-4 py-1.5 bg-gray-200 hover:bg-gray-300 text-gray-700 text-sm rounded-sm transition-colors"
                  >
                    Annuler
                  </button>
                </div>
              </div>
            )}

            {/* Recap List */}
            {loadingRecaps ? (
              <p className="text-xs text-gray-400 text-center py-4">Chargement...</p>
            ) : recaps.length === 0 && !showRecapCreate ? (
              <p className="text-xs text-gray-400 text-center py-4">Aucun recap configuré</p>
            ) : (
              <div className="space-y-2">
                {recaps.map(recap => (
                  <div key={recap.id} className="bg-white rounded-sm border border-amber-100 overflow-hidden">
                    {/* Recap Header */}
                    <div
                      className="flex items-center justify-between p-3 cursor-pointer hover:bg-amber-50 transition-colors"
                      onClick={() => {
                        if (currentRecap?.id === recap.id) {
                          setCurrentRecap(null);
                          setRecapDocuments([]);
                        } else {
                          setCurrentRecap(recap);
                          loadRecapDocuments(recap.id);
                        }
                      }}
                    >
                      <div className="flex items-center gap-2">
                        <span className={`w-2 h-2 rounded-full ${recap.enabled ? 'bg-green-400' : 'bg-gray-300'}`} />
                        <span className="text-sm font-medium text-gray-700">{recap.name}</span>
                        <span className="text-xs text-gray-400">
                          {recap.frequency === 'daily' ? 'Quotidien' : recap.frequency === 'weekly' ? 'Hebdo' : 'Mensuel'} - {recap.hour}h
                        </span>
                      </div>
                      <div className="flex items-center gap-2">
                        <span className="text-xs text-gray-400">{recap.document_count} docs</span>
                        <ChevronDown className={`w-4 h-4 text-gray-400 transition-transform ${currentRecap?.id === recap.id ? 'rotate-180' : ''}`} />
                      </div>
                    </div>

                    {/* Recap Detail (expanded) */}
                    {currentRecap?.id === recap.id && (
                      <div className="border-t border-amber-100 p-3 space-y-3">
                        {/* Toggle enabled */}
                        <div className="flex items-center justify-between">
                          <span className="text-xs font-semibold text-gray-600">Activé</span>
                          <button
                            type="button"
                            className={`w-12 h-6 flex items-center rounded-full px-0.5 transition-colors ${recap.enabled ? 'bg-amber-500' : 'bg-gray-200'}`}
                            onClick={() => updateRecap(recap.id, { enabled: !recap.enabled })}
                          >
                            <span className={`h-5 w-5 rounded-full bg-white shadow transition-transform ${recap.enabled ? 'translate-x-6' : 'translate-x-0'}`} />
                          </button>
                        </div>

                        {/* Name */}
                        <div>
                          <label className="text-xs font-semibold text-gray-600 mb-1 block">Nom</label>
                          <input
                            type="text"
                            className="w-full px-3 py-1.5 border border-amber-200 rounded-sm text-sm"
                            defaultValue={recap.name}
                            onBlur={e => {
                              if (e.target.value.trim() && e.target.value !== recap.name) {
                                updateRecap(recap.id, { name: e.target.value.trim() });
                              }
                            }}
                          />
                        </div>

                        {/* Frequency + Hour */}
                        <div className="grid grid-cols-2 gap-2">
                          <div>
                            <label className="text-xs font-semibold text-gray-600 mb-1 block">Fréquence</label>
                            <select
                              className="w-full px-3 py-1.5 border border-amber-200 rounded-sm text-sm bg-white"
                              value={recap.frequency}
                              onChange={e => updateRecap(recap.id, { frequency: e.target.value })}
                            >
                              {["daily", "weekly", "monthly"].map(freq => (
                                <option key={freq} value={freq}>
                                  {t(`agents:form.weeklyRecap.frequencyOptions.${freq}`)}
                                </option>
                              ))}
                            </select>
                          </div>
                          <div>
                            <label className="text-xs font-semibold text-gray-600 mb-1 block">Heure</label>
                            <select
                              className="w-full px-3 py-1.5 border border-amber-200 rounded-sm text-sm bg-white"
                              value={recap.hour}
                              onChange={e => updateRecap(recap.id, { hour: parseInt(e.target.value, 10) })}
                            >
                              {Array.from({ length: 24 }, (_, i) => (
                                <option key={i} value={i}>{i}h</option>
                              ))}
                            </select>
                          </div>
                        </div>

                        {/* Custom Prompt */}
                        <div>
                          <label className="text-xs font-semibold text-gray-600 mb-1 block">Prompt personnalisé</label>
                          <textarea
                            className="w-full px-3 py-1.5 border border-amber-200 rounded-sm text-sm resize-y"
                            rows={3}
                            placeholder="Personnalisez le contenu du recap..."
                            defaultValue={recap.prompt || ''}
                            onBlur={e => {
                              const val = e.target.value.trim();
                              if (val !== (recap.prompt || '')) {
                                updateRecap(recap.id, { prompt: val || null });
                              }
                            }}
                          />
                        </div>

                        {/* Recipients */}
                        <div>
                          <label className="text-xs font-semibold text-gray-600 mb-1 block">
                            <Users className="w-3.5 h-3.5 inline mr-1 text-amber-600" />
                            Destinataires supplémentaires
                          </label>
                          <div className="flex gap-2">
                            <input
                              type="email"
                              className="flex-1 px-3 py-1.5 border border-amber-200 rounded-sm text-sm"
                              placeholder="email@exemple.com"
                              value={recapRecipientInputNew}
                              onChange={e => setRecapRecipientInputNew(e.target.value)}
                              onKeyDown={e => {
                                if (e.key === 'Enter') {
                                  e.preventDefault();
                                  const email = recapRecipientInputNew.trim();
                                  if (email && /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email) && !(recap.recipients || []).includes(email)) {
                                    updateRecap(recap.id, { recipients: [...(recap.recipients || []), email] });
                                    setRecapRecipientInputNew('');
                                  }
                                }
                              }}
                            />
                            <button
                              type="button"
                              onClick={() => {
                                const email = recapRecipientInputNew.trim();
                                if (email && /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email) && !(recap.recipients || []).includes(email)) {
                                  updateRecap(recap.id, { recipients: [...(recap.recipients || []), email] });
                                  setRecapRecipientInputNew('');
                                }
                              }}
                              className="px-3 py-1.5 bg-amber-500 hover:bg-amber-600 text-white text-sm rounded-sm"
                            >
                              <Plus className="w-4 h-4" />
                            </button>
                          </div>
                          {(recap.recipients || []).length > 0 && (
                            <div className="flex flex-wrap gap-1.5 mt-2">
                              {(recap.recipients || []).map((email, i) => (
                                <span key={i} className="inline-flex items-center gap-1 px-2 py-1 bg-amber-100 text-amber-800 text-xs rounded-full">
                                  <Mail className="w-3 h-3" />
                                  {email}
                                  <button
                                    type="button"
                                    onClick={() => updateRecap(recap.id, { recipients: recap.recipients.filter((_, idx) => idx !== i) })}
                                    className="ml-0.5 hover:text-red-600"
                                  >
                                    <XCircle className="w-3.5 h-3.5" />
                                  </button>
                                </span>
                              ))}
                            </div>
                          )}
                        </div>

                        {/* Documents */}
                        <div>
                          <div className="flex items-center justify-between mb-1">
                            <label className="text-xs font-semibold text-gray-600">Documents</label>
                            <label className="flex items-center gap-1 text-xs text-amber-600 hover:text-amber-700 cursor-pointer">
                              {uploadingRecapDoc ? <Loader2 className="w-3 h-3 animate-spin" /> : <Upload className="w-3 h-3" />}
                              <span>{uploadingRecapDoc ? 'Upload...' : 'Ajouter'}</span>
                              <input
                                type="file"
                                className="hidden"
                                accept=".pdf,.txt,.docx,.xlsx,.xls,.csv,.json"
                                disabled={uploadingRecapDoc}
                                onChange={(e) => {
                                  if (e.target.files[0]) {
                                    uploadRecapDoc(recap.id, e.target.files[0]);
                                    e.target.value = '';
                                  }
                                }}
                              />
                            </label>
                          </div>
                          {recapDocuments.length === 0 ? (
                            <p className="text-xs text-gray-400">Aucun document</p>
                          ) : (
                            <div className="max-h-48 overflow-y-auto space-y-1">
                              {recapDocuments.map(doc => (
                                <div key={doc.document_id} className="flex items-center justify-between p-2 bg-gray-50 rounded-sm">
                                  <span className="text-xs text-gray-700 truncate flex-1 mr-2">{doc.filename}</span>
                                  <button
                                    type="button"
                                    className="text-gray-400 hover:text-red-500 transition-colors"
                                    onClick={() => removeRecapDoc(recap.id, doc.document_id)}
                                    title="Retirer du recap"
                                  >
                                    <Trash2 className="w-3.5 h-3.5" />
                                  </button>
                                </div>
                              ))}
                            </div>
                          )}
                        </div>

                        {/* Action Buttons */}
                        <div className="flex gap-2 pt-2 border-t border-amber-100">
                          <button
                            type="button"
                            onClick={() => sendRecapById(recap.id)}
                            disabled={sendingRecapId === recap.id}
                            className="flex-1 flex items-center justify-center gap-2 px-4 py-2 bg-amber-500 hover:bg-amber-600 disabled:bg-amber-300 text-white text-sm font-medium rounded-sm transition-colors"
                          >
                            {sendingRecapId === recap.id ? <Loader2 className="w-4 h-4 animate-spin" /> : <Send className="w-4 h-4" />}
                            {sendingRecapId === recap.id ? 'Envoi...' : 'Envoyer maintenant'}
                          </button>
                          <button
                            type="button"
                            onClick={() => { if (confirm('Supprimer ce recap ?')) deleteRecap(recap.id); }}
                            className="px-4 py-2 bg-red-100 hover:bg-red-200 text-red-600 text-sm font-medium rounded-sm transition-colors"
                          >
                            <Trash2 className="w-4 h-4" />
                          </button>
                        </div>
                      </div>
                    )}
                  </div>
                ))}
              </div>
            )}
          </div>
        </Section>

        {/* Notion Links */}
        <Section
          icon={Link}
          title={t('agents:notion.title', { count: notionLinks.length })}
          subtitle={t('agents:settings.notionDesc')}
          color="bg-primary-500"
          defaultOpen={false}
        >
          {/* Add Notion link form */}
          <div className="p-4 bg-gradient-to-br from-primary-50 to-violet-50 rounded-button border border-primary-100 mb-4">
            <input
              type="text"
              className="w-full px-4 py-2.5 border border-primary-100 rounded-input focus:border-primary-500 focus:ring-2 focus:ring-primary-100 transition-all outline-none bg-white text-sm mb-3"
              placeholder={t('agents:notion.placeholder')}
              value={notionInput}
              onChange={e => setNotionInput(e.target.value)}
              onKeyDown={e => { if (e.key === 'Enter' && notionInput.trim()) { e.preventDefault(); addNotionLink(); } }}
            />
            <div className="flex gap-2">
              <select
                className="flex-1 px-3 py-2 border border-primary-100 rounded-input focus:border-primary-500 focus:ring-2 focus:ring-primary-100 transition-all outline-none bg-white text-sm"
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
                className="px-4 py-2 bg-primary-600 text-white rounded-button hover:bg-primary-700 transition-colors text-sm font-medium disabled:opacity-50 disabled:cursor-not-allowed flex items-center"
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
              <div key={link.id} className="flex items-center justify-between p-3 bg-white rounded-button border border-gray-200 hover:border-primary-100 transition-all group">
                <div className="flex items-center space-x-3 flex-1 min-w-0">
                  <Link className="w-5 h-5 text-primary-600 flex-shrink-0" />
                  <div className="flex-1 min-w-0">
                    <p className="text-sm font-medium text-gray-900 truncate">{link.label}</p>
                    <p className="text-xs text-gray-500">
                      {link.resource_type === 'page' ? t('agents:notion.typePage') : t('agents:notion.typeDatabase')} &middot; {new Date(link.created_at).toLocaleDateString('fr-FR')}
                    </p>
                  </div>
                </div>
                <div className="flex items-center space-x-1">
                  {link.ingested ? (
                    <span className="flex items-center space-x-1 px-2 py-1 text-xs bg-green-50 text-green-600 rounded-sm border border-green-200">
                      <CheckCircle className="w-3.5 h-3.5" />
                      <span>{t('agents:notion.ingested')}</span>
                    </span>
                  ) : (
                    <button
                      onClick={() => ingestNotionLink(link.id)}
                      disabled={ingestingNotionLinkId === link.id}
                      className="flex items-center space-x-1 px-2 py-1 text-xs text-primary-600 hover:bg-primary-50 rounded-sm transition-all opacity-0 group-hover:opacity-100 disabled:opacity-50"
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
                  <button onClick={() => deleteNotionLink(link.id)} className="p-2 text-gray-400 hover:text-red-600 hover:bg-red-50 rounded-sm transition-all opacity-0 group-hover:opacity-100" title={t('agents:buttons.delete')}>
                    <Trash2 className="w-4 h-4" />
                  </button>
                </div>
              </div>
            ))}
          </div>
        </Section>

        {/* Google Drive */}
        <Section
          icon={HardDrive}
          title={t('agents:drive.title', { count: driveLinks.length })}
          subtitle={t('agents:settings.driveDesc')}
          color="bg-emerald-500"
          defaultOpen={false}
        >
          {/* Add Drive folder form */}
          <div className="p-4 bg-gradient-to-br from-emerald-50 to-teal-50 rounded-button border border-emerald-200 mb-4">
            <div className="flex gap-2">
              <input
                type="text"
                className="flex-1 px-4 py-2.5 border border-emerald-200 rounded-input focus:border-emerald-500 focus:ring-2 focus:ring-emerald-200 transition-all outline-none bg-white text-sm"
                placeholder={t('agents:drive.urlPlaceholder')}
                value={driveInput}
                onChange={e => setDriveInput(e.target.value)}
                onKeyDown={e => { if (e.key === 'Enter' && driveInput.trim()) { e.preventDefault(); addDriveLink(); } }}
              />
              <button
                type="button"
                onClick={addDriveLink}
                disabled={addingDriveLink || !driveInput.trim()}
                className="px-4 py-2 bg-emerald-600 text-white rounded-button hover:bg-emerald-700 transition-colors text-sm font-medium disabled:opacity-50 disabled:cursor-not-allowed flex items-center"
              >
                {addingDriveLink ? <Loader2 className="w-4 h-4 animate-spin" /> : t('agents:drive.addButton')}
              </button>
            </div>
          </div>

          {/* Drive links list */}
          <div className="space-y-2 max-h-64 overflow-y-auto">
            {driveLinks.length === 0 ? (
              <div className="text-center py-6 text-gray-400">
                <HardDrive className="w-10 h-10 mx-auto mb-2 opacity-50" />
                <p className="text-sm">{t('agents:drive.noLinks')}</p>
              </div>
            ) : driveLinks.map(link => (
              <div key={link.id} className="flex items-center justify-between p-3 bg-white rounded-button border border-gray-200 hover:border-emerald-300 transition-all group">
                <div className="flex items-center space-x-3 flex-1 min-w-0">
                  <HardDrive className="w-5 h-5 text-emerald-600 flex-shrink-0" />
                  <div className="flex-1 min-w-0">
                    <p className="text-sm font-medium text-gray-900 truncate">{link.label}</p>
                    <p className="text-xs text-gray-500">
                      {link.ingested_count > 0 ? `${link.ingested_count} ${t('agents:drive.filesIngested')}` : ''} {link.ingested_count > 0 ? '·' : ''} {new Date(link.created_at).toLocaleDateString('fr-FR')}
                    </p>
                  </div>
                </div>
                <div className="flex items-center space-x-1">
                  <button
                    onClick={() => link.ingested_count > 0 ? resyncDriveLink(link.id) : ingestDriveLink(link.id)}
                    disabled={syncingDriveLinkId === link.id}
                    className="flex items-center space-x-1 px-2 py-1 text-xs text-emerald-600 hover:bg-emerald-50 rounded-sm transition-all opacity-0 group-hover:opacity-100 disabled:opacity-50"
                  >
                    {syncingDriveLinkId === link.id ? (
                      <Loader2 className="w-3.5 h-3.5 animate-spin" />
                    ) : (
                      <>
                        <RefreshCw className="w-3.5 h-3.5" />
                        <span>{link.ingested_count > 0 ? t('agents:drive.resyncButton') : t('agents:drive.syncButton')}</span>
                      </>
                    )}
                  </button>
                  <button onClick={() => deleteDriveLink(link.id)} className="p-2 text-gray-400 hover:text-red-600 hover:bg-red-50 rounded-sm transition-all opacity-0 group-hover:opacity-100" title={t('agents:buttons.delete')}>
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
              <div className="flex items-center justify-between p-4 bg-gradient-to-br from-green-50 to-emerald-50 rounded-button border border-green-200">
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
                <div className="p-3 bg-gray-50 rounded-button border border-gray-200">
                  <p className="text-xs font-medium text-gray-500 mb-1">{t('agents:slack.botToken')}</p>
                  <p className="text-sm font-mono text-gray-700">{slackConfig.masked_token}</p>
                </div>
                <div className="p-3 bg-gray-50 rounded-button border border-gray-200">
                  <p className="text-xs font-medium text-gray-500 mb-1">{t('agents:slack.signingSecret')}</p>
                  <p className="text-sm font-mono text-gray-700">{slackConfig.masked_secret}</p>
                </div>
              </div>

              {/* Webhook URL */}
              <div className="p-4 bg-gradient-to-br from-pink-50 to-purple-50 rounded-button border border-pink-200">
                <p className="text-xs font-medium text-gray-500 mb-1">{t('agents:slack.webhookUrl')}</p>
                <div className="flex items-center gap-2">
                  <code className="flex-1 text-sm bg-white px-3 py-2 rounded-sm border border-pink-200 text-gray-700 truncate">
                    {apiUrl}/slack/events
                  </code>
                  <button
                    type="button"
                    onClick={() => { navigator.clipboard.writeText(`${apiUrl}/slack/events`); toast.success(t('agents:slack.copied')); }}
                    className="p-2 text-pink-600 hover:bg-pink-100 rounded-sm transition-colors flex-shrink-0"
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
                  className="flex-1 flex items-center justify-center space-x-2 px-4 py-2.5 bg-pink-600 text-white rounded-button hover:bg-pink-700 transition-colors text-sm font-medium disabled:opacity-50"
                >
                  {testingSlack ? <Loader2 className="w-4 h-4 animate-spin" /> : <Zap className="w-4 h-4" />}
                  <span>{testingSlack ? t('agents:slack.testing') : t('agents:slack.test')}</span>
                </button>
                <button
                  type="button"
                  onClick={disconnectSlack}
                  className="flex items-center justify-center space-x-2 px-4 py-2.5 bg-red-100 text-red-700 rounded-button hover:bg-red-200 transition-colors text-sm font-medium"
                >
                  <XCircle className="w-4 h-4" />
                  <span>{t('agents:slack.disconnect')}</span>
                </button>
              </div>
            </div>
          ) : (
            <div className="space-y-4">
              {/* Not connected status */}
              <div className="flex items-center space-x-3 p-3 bg-gray-50 rounded-button border border-gray-200">
                <XCircle className="w-5 h-5 text-gray-400" />
                <p className="text-sm text-gray-500">{t('agents:slack.notConnected')}</p>
              </div>

              {/* Connection form */}
              <div className="p-4 bg-gradient-to-br from-pink-50 to-purple-50 rounded-button border border-pink-200 space-y-3">
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
                  className="w-full flex items-center justify-center space-x-2 px-4 py-2.5 bg-pink-600 text-white rounded-button hover:bg-pink-700 transition-colors text-sm font-medium disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  {savingSlack ? <Loader2 className="w-4 h-4 animate-spin" /> : <Hash className="w-4 h-4" />}
                  <span>{savingSlack ? t('agents:slack.connecting') : t('agents:slack.connect')}</span>
                </button>
              </div>

              {/* Webhook URL hint */}
              <div className="p-3 bg-gray-50 rounded-button border border-gray-200">
                <p className="text-xs font-medium text-gray-500 mb-1">{t('agents:slack.webhookUrl')}</p>
                <div className="flex items-center gap-2">
                  <code className="flex-1 text-xs bg-white px-2 py-1.5 rounded-sm border border-gray-200 text-gray-600 truncate">
                    {apiUrl}/slack/events
                  </code>
                  <button
                    type="button"
                    onClick={() => { navigator.clipboard.writeText(`${apiUrl}/slack/events`); toast.success(t('agents:slack.copied')); }}
                    className="p-1.5 text-gray-500 hover:bg-gray-100 rounded-sm transition-colors flex-shrink-0"
                  >
                    <Copy className="w-3.5 h-3.5" />
                  </button>
                </div>
                <p className="text-xs text-gray-500 mt-1">{t('agents:slack.webhookHelp')}</p>
              </div>
            </div>
          )}
        </Section>

        {/* Mobile Chat Button + auto-save indicator */}
        <div className="sm:hidden sticky bottom-4 flex flex-col gap-2">
          {autoSaveStatus !== 'idle' && (
            <div className="flex items-center justify-center gap-1.5 py-1 text-sm">
              {autoSaveStatus === 'saving' && <><Loader2 className="w-3.5 h-3.5 animate-spin text-gray-400" /><span className="text-gray-400">{t('agents:autosave.saving')}</span></>}
              {autoSaveStatus === 'saved' && <><Check className="w-3.5 h-3.5 text-green-600" /><span className="text-green-600">{t('agents:autosave.saved')}</span></>}
              {autoSaveStatus === 'error' && <><AlertCircle className="w-3.5 h-3.5 text-red-500" /><span className="text-red-500" onClick={() => saveAgent()}>{t('agents:autosave.error')}</span></>}
            </div>
          )}
          {currentAgent?.id && (
            <button
              onClick={() => router.push(`/chat/${currentAgent.id}`)}
              className="w-full flex items-center justify-center space-x-2 px-6 py-4 bg-gradient-to-r from-blue-600 to-purple-600 hover:from-blue-700 hover:to-purple-700 text-white rounded-button font-semibold shadow-card hover:shadow-elevated transition-all"
            >
              <MessageCircle className="w-5 h-5" />
              <span>{t('agents:buttons.openChat')}</span>
            </button>
          )}
        </div>

        {/* Bottom spacer */}
        <div className="h-8" />
      </div>

      {/* Improve Context Modal */}
      {showImproveModal && improvedContext && (
        <div className="fixed inset-0 bg-black/50 backdrop-blur-sm flex items-center justify-center z-[100] p-4">
          <div className="bg-white rounded-card shadow-floating w-full max-w-4xl mx-auto max-h-[85vh] overflow-auto border border-gray-200 animate-fade-in">
            <div className="flex items-center justify-between px-6 py-4 border-b border-gray-200">
              <div className="flex items-center gap-2">
                <Sparkles className="w-5 h-5 text-amber-500" />
                <h2 className="text-lg font-heading font-bold text-gray-900">
                  {t('agents:improve.title')}
                </h2>
              </div>
              <button
                onClick={() => { setShowImproveModal(false); setImprovedContext(null); }}
                className="p-1.5 text-gray-400 hover:text-gray-600 hover:bg-gray-100 rounded-sm transition-colors"
              >
                <XCircle className="w-5 h-5" />
              </button>
            </div>

            <div className="grid grid-cols-1 md:grid-cols-2 gap-4 p-6">
              <div>
                <label className="text-sm font-semibold text-gray-500 mb-2 block uppercase tracking-wide">
                  {t('agents:improve.original')}
                </label>
                <div className="p-4 bg-gray-50 border border-gray-200 rounded-input text-sm text-gray-700 whitespace-pre-wrap min-h-[200px] max-h-[400px] overflow-auto">
                  {form.contexte}
                </div>
              </div>
              <div>
                <label className="text-sm font-semibold text-amber-600 mb-2 block uppercase tracking-wide flex items-center gap-1">
                  <Sparkles className="w-3.5 h-3.5" />
                  {t('agents:improve.improved')}
                </label>
                <div className="p-4 bg-amber-50 border border-amber-200 rounded-input text-sm text-gray-700 whitespace-pre-wrap min-h-[200px] max-h-[400px] overflow-auto">
                  {improvedContext}
                </div>
              </div>
            </div>

            <div className="flex items-center justify-end gap-3 px-6 py-4 border-t border-gray-200 bg-gray-50">
              <button
                onClick={() => { setShowImproveModal(false); setImprovedContext(null); }}
                className="px-5 py-2.5 text-gray-700 bg-white border border-gray-300 rounded-button hover:bg-gray-50 font-semibold text-sm transition-colors"
              >
                {t('agents:improve.cancel')}
              </button>
              <button
                onClick={acceptImprovedContext}
                className="px-5 py-2.5 bg-gradient-to-r from-amber-500 to-orange-500 hover:from-amber-600 hover:to-orange-600 text-white rounded-button font-semibold text-sm shadow-sm hover:shadow-card transition-all flex items-center gap-2"
              >
                <CheckCircle className="w-4 h-4" />
                {t('agents:improve.accept')}
              </button>
            </div>
          </div>
        </div>
      )}
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
