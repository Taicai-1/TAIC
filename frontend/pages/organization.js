import { useState, useEffect } from 'react';
import { useRouter } from 'next/router';
import { useTranslation } from 'next-i18next';
import { serverSideTranslations } from 'next-i18next/serverSideTranslations';
import Layout from '../components/Layout';
import toast, { Toaster } from 'react-hot-toast';
import { useAuth } from '../hooks/useAuth';
import api from '../lib/api';
import {
  ArrowLeft,
  Building2,
  Users,
  Mail,
  Shield,
  Crown,
  UserPlus,
  Copy,
  RefreshCw,
  Trash2,
  Bot,
  Loader2,
  Link2,
  ToggleLeft,
  ToggleRight,
  LogOut,
  Settings,
  Eye,
  EyeOff,
  FileText,
  ChevronDown,
  ChevronUp,
  Share2,
  X,
  XCircle,
  Zap,
  Edit3,
} from 'lucide-react';

export default function Organization() {
  const router = useRouter();
  const { t } = useTranslation(['organization', 'common', 'errors']);
  const { user: authUser, loading: authLoading, authenticated } = useAuth();

  const [loading, setLoading] = useState(true);
  const [company, setCompany] = useState(null);

  // No-org state
  const [createName, setCreateName] = useState('');
  const [joinCode, setJoinCode] = useState('');
  const [actionLoading, setActionLoading] = useState(false);

  // Org creation request state
  const [myRequest, setMyRequest] = useState(null); // { id, requested_name, status, created_at, decided_reason }

  // Members
  const [members, setMembers] = useState([]);
  const [membersOpen, setMembersOpen] = useState(true);

  // Invitations
  const [inviteEmail, setInviteEmail] = useState('');
  const [inviteRole, setInviteRole] = useState('member');
  const [inviteLoading, setInviteLoading] = useState(false);

  // Integrations
  const [integrations, setIntegrations] = useState(null);
  const [integForm, setIntegForm] = useState({
    neo4j_uri: '', neo4j_user: '', neo4j_password: '',
    notion_api_key: '',
  });
  const [integLoading, setIntegLoading] = useState(false);
  const [showSecrets, setShowSecrets] = useState({});

  // Org agents
  const [orgAgents, setOrgAgents] = useState([]);
  const [agentsOpen, setAgentsOpen] = useState(false);

  // Share modal
  const [shareModalAgent, setShareModalAgent] = useState(null);
  const [agentShares, setAgentShares] = useState([]);
  const [shareTargetUserId, setShareTargetUserId] = useState('');
  const [shareCanEdit, setShareCanEdit] = useState(false);
  const [shareLoading, setShareLoading] = useState(false);

  // Slash commands
  const [slashCommands, setSlashCommands] = useState([]);
  const [slashModalOpen, setSlashModalOpen] = useState(false);
  const [slashEditItem, setSlashEditItem] = useState(null);
  const [slashForm, setSlashForm] = useState({ command: '', prompt: '', agent_ids: [] });
  const [slashLoading, setSlashLoading] = useState(false);
  const [slashOpen, setSlashOpen] = useState(false);

  useEffect(() => {
    if (!authenticated) return;
    loadCompany();
  }, [authenticated]);

  const loadCompany = async () => {
    setLoading(true);
    try {
      const res = await api.get('/api/companies/mine');
      const data = res.data;
      setCompany(data.company);

      // If no company, check for a pending/rejected request
      if (!data.company) {
        try {
          const reqRes = await api.get('/api/companies/request/mine');
          setMyRequest(reqRes.data.request);
        } catch {
          setMyRequest(null);
        }
      } else {
        setMyRequest(null);
      }

      if (data.company && ['admin', 'owner'].includes(data.company.role)) {
        loadMembers();
        loadOrgAgents();
        loadSlashCommands();
        if (data.company.role === 'owner') loadIntegrations();
      }
    } catch (error) {
      toast.error(error.response?.data?.detail || t('organization:errors.loadFailed'));
    } finally {
      setLoading(false);
    }
  };

  const loadMembers = async () => {
    try {
      const res = await api.get('/api/companies/members');
      const data = res.data;
      setMembers(data.members || []);
    } catch {}
  };

  const loadIntegrations = async () => {
    try {
      const res = await api.get('/api/companies/integrations');
      const data = res.data;
      setIntegrations(data);
    } catch {}
  };

  const loadOrgAgents = async () => {
    try {
      const res = await api.get('/api/companies/agents');
      const data = res.data;
      setOrgAgents(data.agents || []);
    } catch {}
  };

  const loadSlashCommands = async () => {
    try {
      const res = await api.get('/api/companies/slash-commands');
      setSlashCommands(res.data.slash_commands || []);
    } catch {}
  };

  const handleSaveSlashCommand = async () => {
    if (!slashForm.command.trim() || !slashForm.prompt.trim()) {
      toast.error(t('organization:slashCommands.errors.requiredFields'));
      return;
    }
    setSlashLoading(true);
    try {
      let updated;
      if (slashEditItem) {
        updated = slashCommands.map(c =>
          c.id === slashEditItem.id
            ? { ...c, command: slashForm.command.toLowerCase(), prompt: slashForm.prompt, agent_ids: slashForm.agent_ids }
            : c
        );
      } else {
        updated = [...slashCommands, {
          command: slashForm.command.toLowerCase(),
          prompt: slashForm.prompt,
          agent_ids: slashForm.agent_ids,
        }];
      }
      const res = await api.put('/api/companies/slash-commands', { slash_commands: updated });
      setSlashCommands(res.data.slash_commands || []);
      setSlashModalOpen(false);
      setSlashEditItem(null);
      setSlashForm({ command: '', prompt: '', agent_ids: [] });
      toast.success(slashEditItem ? t('organization:slashCommands.updated') : t('organization:slashCommands.created'));
    } catch (error) {
      toast.error(error.response?.data?.detail || t('organization:errors.generic'));
    } finally {
      setSlashLoading(false);
    }
  };

  const handleDeleteSlashCommand = (id) => {
    if (!confirm(t('organization:slashCommands.deleteConfirm'))) return;
    const updated = slashCommands.filter(c => c.id !== id);
    api.put('/api/companies/slash-commands', { slash_commands: updated })
      .then(res => {
        setSlashCommands(res.data.slash_commands || []);
        toast.success(t('organization:slashCommands.deleted'));
      })
      .catch(error => toast.error(error.response?.data?.detail || t('organization:errors.generic')));
  };

  const openSlashEdit = (item) => {
    setSlashEditItem(item);
    setSlashForm({ command: item.command, prompt: item.prompt, agent_ids: item.agent_ids || [] });
    setSlashModalOpen(true);
  };

  const openSlashCreate = () => {
    setSlashEditItem(null);
    setSlashForm({ command: '', prompt: '', agent_ids: [] });
    setSlashModalOpen(true);
  };

  // ---- No-org actions ----
  const handleCreate = async () => {
    if (!createName.trim()) return;
    setActionLoading(true);
    try {
      await api.post('/api/companies/request', { name: createName.trim() });
      toast.success(t('organization:noOrg.requestSubmitted'));
      setCreateName('');
      // Refresh to show pending state
      loadCompany();
    } catch (error) {
      toast.error(error.response?.data?.detail || t('organization:errors.generic'));
    } finally {
      setActionLoading(false);
    }
  };

  const handleJoin = async () => {
    if (!joinCode.trim()) return;
    setActionLoading(true);
    try {
      const res = await api.post('/api/companies/join', { invite_code: joinCode.trim() });
      const data = res.data;
      toast.success(data.message);
      loadCompany();
      setJoinCode('');
    } catch (error) {
      toast.error(error.response?.data?.detail || t('organization:errors.generic'));
    } finally {
      setActionLoading(false);
    }
  };

  // ---- Leave ----
  const handleLeave = async () => {
    if (!confirm(t('organization:info.leaveConfirm'))) return;
    try {
      await api.post('/api/companies/leave');
      toast.success('OK');
      setCompany(null);
      setMembers([]);
      setOrgAgents([]);
    } catch (error) {
      toast.error(error.response?.data?.detail || t('organization:errors.generic'));
    }
  };

  // ---- Delete org (owner) ----
  const handleDeleteOrg = async () => {
    if (!confirm(t('organization:info.deleteConfirm'))) return;
    try {
      await api.delete('/api/companies');
      toast.success('OK');
      setCompany(null);
      setMembers([]);
      setOrgAgents([]);
    } catch (error) {
      toast.error(error.response?.data?.detail || t('organization:errors.generic'));
    }
  };

  // ---- Invitations ----
  const handleSendInvite = async () => {
    if (!inviteEmail.trim()) return;
    setInviteLoading(true);
    try {
      await api.post('/api/companies/invite', { email: inviteEmail.trim(), role: inviteRole });
      toast.success(t('organization:invitations.sent'));
      setInviteEmail('');
    } catch (error) {
      toast.error(error.response?.data?.detail || t('organization:errors.generic'));
    } finally {
      setInviteLoading(false);
    }
  };

  const handleCopyInviteLink = () => {
    if (!company?.invite_code) return;
    navigator.clipboard.writeText(company.invite_code);
    toast.success(t('organization:invitations.copied'));
  };

  const handleToggleCode = async () => {
    try {
      await api.put('/api/companies/invite-code/toggle', { enabled: !company.invite_code_enabled });
      setCompany(prev => ({ ...prev, invite_code_enabled: !prev.invite_code_enabled }));
    } catch (error) {
      toast.error(error.response?.data?.detail || t('organization:errors.generic'));
    }
  };

  const handleRegenerateCode = async () => {
    if (!confirm(t('organization:invitations.regenerateConfirm'))) return;
    try {
      const res = await api.post('/api/companies/invite-code/regenerate');
      const data = res.data;
      setCompany(prev => ({ ...prev, invite_code: data.invite_code }));
      toast.success(t('organization:invitations.regenerated'));
    } catch (error) {
      toast.error(error.response?.data?.detail || t('organization:errors.generic'));
    }
  };

  // ---- Members ----
  const handleChangeRole = async (memberId, newRole) => {
    try {
      await api.put(`/api/companies/members/${memberId}/role`, { role: newRole });
      toast.success(t('organization:members.roleUpdated'));
      loadMembers();
    } catch (error) {
      toast.error(error.response?.data?.detail || t('organization:errors.generic'));
    }
  };

  const handleRemoveMember = async (memberId) => {
    if (!confirm(t('organization:members.removeConfirm'))) return;
    try {
      await api.delete(`/api/companies/members/${memberId}`);
      toast.success(t('organization:members.memberRemoved'));
      loadMembers();
    } catch (error) {
      toast.error(error.response?.data?.detail || t('organization:errors.generic'));
    }
  };

  // ---- Integrations ----
  const handleSaveIntegrations = async () => {
    setIntegLoading(true);
    try {
      const body = {};
      Object.entries(integForm).forEach(([k, v]) => { if (v) body[k] = v; });
      await api.put('/api/companies/integrations', body);
      toast.success(t('organization:integrations.saved'));
      setIntegForm({ neo4j_uri: '', neo4j_user: '', neo4j_password: '', notion_api_key: '' });
      loadIntegrations();
    } catch (error) {
      toast.error(error.response?.data?.detail || t('organization:errors.generic'));
    } finally {
      setIntegLoading(false);
    }
  };

  const handleDeleteIntegration = async (type) => {
    if (!confirm(t('organization:integrations.removeConfirm'))) return;
    setIntegLoading(true);
    try {
      const body = type === 'neo4j'
        ? { neo4j_uri: '', neo4j_user: '', neo4j_password: '' }
        : { notion_api_key: '' };
      await api.put('/api/companies/integrations', body);
      toast.success(t('organization:integrations.removed'));
      loadIntegrations();
    } catch (error) {
      toast.error(error.response?.data?.detail || t('organization:errors.generic'));
    } finally {
      setIntegLoading(false);
    }
  };

  // ---- Org Agent Actions ----
  const handleDeleteOrgAgent = async (agentId) => {
    if (!confirm(t('organization:agents.deleteConfirm'))) return;
    try {
      await api.delete(`/api/companies/agents/${agentId}`);
      toast.success(t('organization:agents.deleted'));
      loadOrgAgents();
    } catch (error) {
      toast.error(error.response?.data?.detail || t('organization:errors.generic'));
    }
  };

  const openShareModal = async (agent) => {
    setShareModalAgent(agent);
    setShareTargetUserId('');
    setShareCanEdit(false);
    try {
      const res = await api.get(`/api/companies/agents/${agent.id}/shares`);
      const data = res.data;
      setAgentShares(data.shares || []);
    } catch {}
  };

  const handleShare = async () => {
    if (!shareTargetUserId || !shareModalAgent) return;
    setShareLoading(true);
    try {
      await api.post(`/api/companies/agents/${shareModalAgent.id}/share`, {
        user_id: parseInt(shareTargetUserId),
        can_edit: shareCanEdit
      });
      toast.success(t('organization:agents.share') + ' OK');
      openShareModal(shareModalAgent);
      loadOrgAgents();
    } catch (error) {
      toast.error(error.response?.data?.detail || t('organization:errors.generic'));
    } finally {
      setShareLoading(false);
    }
  };

  const handleRemoveShare = async (targetUserId) => {
    if (!shareModalAgent) return;
    try {
      await api.delete(`/api/companies/agents/${shareModalAgent.id}/share/${targetUserId}`);
      toast.success(t('organization:agents.shareRemoved'));
      openShareModal(shareModalAgent);
      loadOrgAgents();
    } catch (error) {
      toast.error(error.response?.data?.detail || t('organization:errors.generic'));
    }
  };

  const handleToggleCanEdit = async (targetUserId, currentCanEdit) => {
    if (!shareModalAgent) return;
    try {
      await api.put(`/api/companies/agents/${shareModalAgent.id}/share/${targetUserId}`, {
        can_edit: !currentCanEdit
      });
      openShareModal(shareModalAgent);
    } catch (error) {
      toast.error(error.response?.data?.detail || t('organization:errors.generic'));
    }
  };

  const roleLabel = (role) => t(`organization:members.${role}`);
  const roleBadge = (role) => {
    const colors = { owner: 'bg-yellow-100 text-yellow-800', admin: 'bg-blue-100 text-blue-800', member: 'bg-gray-100 text-gray-700' };
    const icons = { owner: <Crown className="w-3 h-3 mr-1" />, admin: <Shield className="w-3 h-3 mr-1" />, member: null };
    return (
      <span className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium ${colors[role] || colors.member}`}>
        {icons[role]}{roleLabel(role)}
      </span>
    );
  };

  // ---- Render ----
  if (authLoading || loading) {
    return (
      <div className="min-h-screen bg-gray-50 flex items-center justify-center">
        <Loader2 className="w-12 h-12 text-primary-600 animate-spin" />
      </div>
    );
  }

  return (
    <Layout showBack backHref="/agents" title={t('organization:pageTitle')}>
      <Toaster position="top-right" />

      <div className="py-8 px-4 sm:px-6 lg:px-8">
        <div className="max-w-5xl mx-auto">
          {/* Subtitle */}
          <div className="mb-8">
            <p className="text-gray-600">{t('organization:pageSubtitle')}</p>
          </div>

          {/* ======== NO ORG ======== */}
          {!company && myRequest?.status === 'pending' && (
            <div className="bg-white rounded-card shadow-card border border-gray-200 p-8 max-w-2xl mx-auto text-center">
              <div className="w-16 h-16 rounded-full bg-gradient-to-br from-amber-400 to-amber-600 flex items-center justify-center mx-auto mb-4">
                <Loader2 className="w-8 h-8 text-white animate-spin" />
              </div>
              <h2 className="text-xl font-heading font-bold text-gray-900 mb-3">
                {t('organization:request.pendingTitle')}
              </h2>
              <p className="text-gray-600 mb-4">
                {t('organization:request.pendingBody', { name: myRequest.requested_name })}
              </p>
              {myRequest.created_at && (
                <p className="text-sm text-gray-400">
                  {t('organization:request.pendingSubmittedAt', {
                    date: new Date(myRequest.created_at).toLocaleDateString()
                  })}
                </p>
              )}
            </div>
          )}

          {!company && myRequest?.status === 'rejected' && (
            <div className="bg-white rounded-card shadow-card border border-gray-200 p-8 max-w-2xl mx-auto">
              <div className="flex flex-col items-center text-center mb-6">
                <div className="w-16 h-16 rounded-full bg-gradient-to-br from-red-400 to-red-600 flex items-center justify-center mb-4">
                  <XCircle className="w-8 h-8 text-white" />
                </div>
                <h2 className="text-xl font-heading font-bold text-gray-900 mb-3">
                  {t('organization:request.rejectedTitle')}
                </h2>
                <p className="text-gray-600 mb-2">
                  {t('organization:request.rejectedBody', { name: myRequest.requested_name })}
                </p>
                {myRequest.decided_reason && (
                  <p className="text-sm text-gray-500 p-3 bg-red-50 border-l-3 border-red-400 rounded mt-3">
                    {t('organization:request.rejectedReason', { reason: myRequest.decided_reason })}
                  </p>
                )}
              </div>
              <button
                onClick={() => setMyRequest(null)}
                className="w-full py-3 bg-gradient-to-r from-teal-500 to-teal-600 hover:from-teal-600 hover:to-teal-700 text-white font-semibold rounded-button shadow-card hover:shadow-elevated transition-all"
              >
                {t('organization:request.retryButton')}
              </button>
            </div>
          )}

          {!company && !myRequest && (
            <div className="grid md:grid-cols-2 gap-6">
              {/* Create */}
              <div className="bg-white rounded-card shadow-card border border-gray-200 p-8">
                <div className="flex items-center space-x-3 mb-6">
                  <div className="w-10 h-10 rounded-button bg-gradient-to-br from-teal-400 to-teal-600 flex items-center justify-center">
                    <Building2 className="w-5 h-5 text-white" />
                  </div>
                  <h2 className="text-xl font-heading font-bold text-gray-900">{t('organization:noOrg.createTitle')}</h2>
                </div>
                <input
                  type="text" className="w-full px-4 py-3 border border-gray-200 rounded-input focus:border-teal-500 focus:ring-2 focus:ring-teal-200 transition-all outline-none bg-white mb-4"
                  placeholder={t('organization:noOrg.namePlaceholder')} value={createName} onChange={e => setCreateName(e.target.value)}
                />
                <button onClick={handleCreate} disabled={actionLoading || !createName.trim()}
                  className="w-full py-3 bg-gradient-to-r from-teal-500 to-teal-600 hover:from-teal-600 hover:to-teal-700 text-white font-semibold rounded-button shadow-card hover:shadow-elevated disabled:opacity-50 disabled:cursor-not-allowed transition-all">
                  {actionLoading ? <Loader2 className="w-5 h-5 animate-spin mx-auto" /> : t('organization:noOrg.createButton')}
                </button>
              </div>

              {/* Join */}
              <div className="bg-white rounded-card shadow-card border border-gray-200 p-8">
                <div className="flex items-center space-x-3 mb-6">
                  <div className="w-10 h-10 rounded-button bg-gradient-to-br from-primary-500 to-primary-600 flex items-center justify-center">
                    <UserPlus className="w-5 h-5 text-white" />
                  </div>
                  <h2 className="text-xl font-heading font-bold text-gray-900">{t('organization:noOrg.joinTitle')}</h2>
                </div>
                <input
                  type="text" className="w-full px-4 py-3 border border-gray-200 rounded-input focus:border-primary-500 focus:ring-2 focus:ring-primary-100 transition-all outline-none bg-white mb-4"
                  placeholder={t('organization:noOrg.codePlaceholder')} value={joinCode} onChange={e => setJoinCode(e.target.value)}
                />
                <button onClick={handleJoin} disabled={actionLoading || !joinCode.trim()}
                  className="w-full py-3 bg-gradient-to-r from-primary-500 to-primary-600 hover:from-primary-600 hover:to-primary-700 text-white font-semibold rounded-button shadow-card hover:shadow-elevated disabled:opacity-50 disabled:cursor-not-allowed transition-all">
                  {actionLoading ? <Loader2 className="w-5 h-5 animate-spin mx-auto" /> : t('organization:noOrg.joinButton')}
                </button>
              </div>
            </div>
          )}

          {/* ======== HAS ORG ======== */}
          {company && (
            <div className="space-y-6">
              {/* Org info card */}
              <div className="bg-white rounded-card shadow-card border border-gray-200 p-8">
                <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4">
                  <div className="flex items-center space-x-4">
                    <div className="w-14 h-14 rounded-card bg-gradient-to-br from-teal-400 to-teal-600 flex items-center justify-center shadow-card">
                      <Building2 className="w-7 h-7 text-white" />
                    </div>
                    <div>
                      <h2 className="text-2xl font-bold text-gray-900">{company.name}</h2>
                      <div className="flex items-center space-x-3 mt-1">
                        {roleBadge(company.role)}
                      </div>
                    </div>
                  </div>
                  {company.role !== 'owner' && (
                    <button onClick={handleLeave}
                      className="flex items-center space-x-2 px-4 py-2 text-red-600 hover:bg-red-50 border border-red-200 rounded-button transition-colors">
                      <LogOut className="w-4 h-4" />
                      <span className="text-sm font-medium">{t('organization:info.leaveButton')}</span>
                    </button>
                  )}
                  {company.role === 'owner' && (
                    <button onClick={handleDeleteOrg}
                      className="flex items-center space-x-2 px-4 py-2 text-red-600 hover:bg-red-50 border border-red-200 rounded-button transition-colors">
                      <Trash2 className="w-4 h-4" />
                      <span className="text-sm font-medium">{t('organization:info.deleteButton')}</span>
                    </button>
                  )}
                </div>
              </div>

              {/* ---- Invitations (admin/owner) ---- */}
              {['admin', 'owner'].includes(company.role) && (
                <div className="bg-white rounded-card shadow-card border border-gray-200 p-8">
                  <div className="flex items-center space-x-3 mb-6">
                    <div className="w-10 h-10 rounded-button bg-gradient-to-br from-purple-400 to-purple-600 flex items-center justify-center">
                      <Mail className="w-5 h-5 text-white" />
                    </div>
                    <h2 className="text-xl font-heading font-bold text-gray-900">{t('organization:invitations.title')}</h2>
                  </div>

                  {/* Invite by email */}
                  <div className="flex flex-col sm:flex-row gap-3 mb-6">
                    <input type="email" className="flex-1 px-4 py-3 border border-gray-200 rounded-input focus:border-purple-500 focus:ring-2 focus:ring-purple-200 transition-all outline-none bg-white"
                      placeholder={t('organization:invitations.emailPlaceholder')} value={inviteEmail} onChange={e => setInviteEmail(e.target.value)} />
                    <select value={inviteRole} onChange={e => setInviteRole(e.target.value)}
                      className="px-4 py-3 border border-gray-200 rounded-input focus:border-purple-500 focus:ring-2 focus:ring-purple-200 transition-all outline-none bg-white">
                      <option value="member">{t('organization:members.member')}</option>
                      <option value="admin">{t('organization:members.admin')}</option>
                    </select>
                    <button onClick={handleSendInvite} disabled={inviteLoading || !inviteEmail.trim()}
                      className="px-6 py-3 bg-gradient-to-r from-purple-500 to-purple-600 hover:from-purple-600 hover:to-purple-700 text-white font-semibold rounded-button shadow-card hover:shadow-elevated disabled:opacity-50 disabled:cursor-not-allowed transition-all whitespace-nowrap">
                      {inviteLoading ? <Loader2 className="w-5 h-5 animate-spin" /> : t('organization:invitations.sendButton')}
                    </button>
                  </div>

                  {/* Invite link */}
                  {company.invite_code && (
                    <div className="p-4 bg-gray-50 rounded-button space-y-3">
                      <div className="flex items-center justify-between">
                        <div className="flex items-center space-x-2">
                          <Link2 className="w-4 h-4 text-gray-500" />
                          <span className="text-sm font-medium text-gray-700">{t('organization:invitations.inviteLink')}</span>
                        </div>
                        <div className="flex items-center space-x-2">
                          <span className={`text-xs font-medium ${company.invite_code_enabled ? 'text-green-600' : 'text-gray-400'}`}>
                            {company.invite_code_enabled ? t('organization:invitations.codeEnabled') : t('organization:invitations.codeDisabled')}
                          </span>
                        </div>
                      </div>
                      <div className="flex items-center gap-2 flex-wrap">
                        <code className="flex-1 px-3 py-2 bg-white border border-gray-200 rounded-sm text-sm font-mono text-gray-600 truncate">
                          {company.invite_code}
                        </code>
                        <button onClick={handleCopyInviteLink} className="p-2 text-gray-500 hover:text-primary-600 hover:bg-primary-50 rounded-sm transition-colors" title={t('organization:invitations.copyLink')}>
                          <Copy className="w-4 h-4" />
                        </button>
                        {company.role === 'owner' && (
                          <>
                            <button onClick={handleToggleCode} className="p-2 text-gray-500 hover:text-purple-600 hover:bg-purple-50 rounded-sm transition-colors">
                              {company.invite_code_enabled ? <ToggleRight className="w-5 h-5 text-green-500" /> : <ToggleLeft className="w-5 h-5 text-gray-400" />}
                            </button>
                            <button onClick={handleRegenerateCode} className="p-2 text-gray-500 hover:text-orange-600 hover:bg-orange-50 rounded-sm transition-colors" title={t('organization:invitations.regenerate')}>
                              <RefreshCw className="w-4 h-4" />
                            </button>
                          </>
                        )}
                      </div>
                    </div>
                  )}
                </div>
              )}

              {/* ---- Members (admin/owner) ---- */}
              {['admin', 'owner'].includes(company.role) && (
                <div className="bg-white rounded-card shadow-card border border-gray-200 p-8">
                  <button onClick={() => setMembersOpen(!membersOpen)} className="w-full flex items-center justify-between mb-4">
                    <div className="flex items-center space-x-3">
                      <div className="w-10 h-10 rounded-button bg-gradient-to-br from-primary-500 to-primary-600 flex items-center justify-center">
                        <Users className="w-5 h-5 text-white" />
                      </div>
                      <h2 className="text-xl font-heading font-bold text-gray-900">{t('organization:members.title')} ({members.length})</h2>
                    </div>
                    {membersOpen ? <ChevronUp className="w-5 h-5 text-gray-400" /> : <ChevronDown className="w-5 h-5 text-gray-400" />}
                  </button>

                  {membersOpen && (
                    <div className="overflow-x-auto">
                      <table className="w-full text-sm">
                        <thead>
                          <tr className="border-b border-gray-200">
                            <th className="text-left py-3 px-2 font-semibold text-gray-600">{t('organization:members.username')}</th>
                            <th className="text-left py-3 px-2 font-semibold text-gray-600 hidden sm:table-cell">{t('organization:members.email')}</th>
                            <th className="text-left py-3 px-2 font-semibold text-gray-600">{t('organization:members.role')}</th>
                            <th className="text-center py-3 px-2 font-semibold text-gray-600">{t('organization:members.agents')}</th>
                            {company.role === 'owner' && (
                              <th className="text-right py-3 px-2 font-semibold text-gray-600">{t('organization:members.actions')}</th>
                            )}
                          </tr>
                        </thead>
                        <tbody>
                          {members.map(m => (
                            <tr key={m.id} className="border-b border-gray-100 hover:bg-gray-50/50 transition-colors">
                              <td className="py-3 px-2 font-medium text-gray-900">{m.username}</td>
                              <td className="py-3 px-2 text-gray-500 hidden sm:table-cell">{m.email}</td>
                              <td className="py-3 px-2">{roleBadge(m.role)}</td>
                              <td className="py-3 px-2 text-center">
                                <span className="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium bg-gray-100 text-gray-700">
                                  <Bot className="w-3 h-3 mr-1" />{m.agent_count}
                                </span>
                              </td>
                              {company.role === 'owner' && (
                                <td className="py-3 px-2 text-right">
                                  {m.role !== 'owner' && (
                                    <div className="flex items-center justify-end space-x-1">
                                      <select
                                        value={m.role}
                                        onChange={e => handleChangeRole(m.id, e.target.value)}
                                        className="text-xs px-2 py-1 border border-gray-200 rounded-sm focus:outline-none focus:ring-1 focus:ring-primary-500"
                                      >
                                        <option value="member">{t('organization:members.member')}</option>
                                        <option value="admin">{t('organization:members.admin')}</option>
                                      </select>
                                      <button onClick={() => handleRemoveMember(m.id)} className="p-1 text-red-400 hover:text-red-600 hover:bg-red-50 rounded-sm transition-colors">
                                        <Trash2 className="w-4 h-4" />
                                      </button>
                                    </div>
                                  )}
                                </td>
                              )}
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  )}
                </div>
              )}

              {/* ---- Integrations (owner only) ---- */}
              {company.role === 'owner' && (
                <div className="bg-white rounded-card shadow-card border border-gray-200 p-8">
                  <div className="flex items-center space-x-3 mb-2">
                    <div className="w-10 h-10 rounded-button bg-gradient-to-br from-orange-400 to-orange-600 flex items-center justify-center">
                      <Settings className="w-5 h-5 text-white" />
                    </div>
                    <h2 className="text-xl font-heading font-bold text-gray-900">{t('organization:integrations.title')}</h2>
                  </div>
                  <p className="text-gray-500 text-sm mb-6 ml-13">{t('organization:integrations.description')}</p>

                  <div className="space-y-6">
                    {/* Neo4j */}
                    <div className="p-4 bg-gray-50 rounded-button space-y-3">
                      <div className="flex items-center justify-between">
                        <h3 className="font-semibold text-gray-800">{t('organization:integrations.neo4j.title')}</h3>
                        <span className={`text-xs font-medium px-2 py-0.5 rounded-full ${integrations?.neo4j?.configured ? 'bg-green-100 text-green-700' : 'bg-gray-100 text-gray-500'}`}>
                          {integrations?.neo4j?.configured ? t('organization:integrations.configured') : t('organization:integrations.notConfigured')}
                        </span>
                      </div>
                      {integrations?.neo4j?.configured ? (
                        <div className="flex items-center justify-between p-3 bg-white border border-green-200 rounded-sm">
                          <div className="space-y-1">
                            <p className="text-sm text-gray-700">
                              <span className="font-medium">{t('organization:integrations.neo4j.uri')}:</span>{' '}
                              <code className="text-xs bg-gray-100 px-1.5 py-0.5 rounded">{integrations.neo4j.uri}</code>
                            </p>
                            {integrations.neo4j.user && (
                              <p className="text-sm text-gray-700">
                                <span className="font-medium">{t('organization:integrations.neo4j.user')}:</span>{' '}
                                <code className="text-xs bg-gray-100 px-1.5 py-0.5 rounded">{integrations.neo4j.user}</code>
                              </p>
                            )}
                          </div>
                          <button onClick={() => handleDeleteIntegration('neo4j')} disabled={integLoading}
                            className="flex items-center space-x-1.5 px-3 py-1.5 text-red-600 hover:bg-red-50 border border-red-200 rounded-sm transition-colors text-sm disabled:opacity-50">
                            <Trash2 className="w-3.5 h-3.5" />
                            <span>{t('organization:integrations.removeButton')}</span>
                          </button>
                        </div>
                      ) : (
                        <div className="grid sm:grid-cols-3 gap-3">
                          <input type="text" placeholder={t('organization:integrations.neo4j.uriPlaceholder')}
                            className="px-3 py-2 border border-gray-200 rounded-sm text-sm focus:outline-none focus:ring-1 focus:ring-orange-500 bg-white"
                            value={integForm.neo4j_uri} onChange={e => setIntegForm(p => ({ ...p, neo4j_uri: e.target.value }))} />
                          <input type="text" placeholder={t('organization:integrations.neo4j.userPlaceholder')}
                            className="px-3 py-2 border border-gray-200 rounded-sm text-sm focus:outline-none focus:ring-1 focus:ring-orange-500 bg-white"
                            value={integForm.neo4j_user} onChange={e => setIntegForm(p => ({ ...p, neo4j_user: e.target.value }))} />
                          <div className="relative">
                            <input type={showSecrets.neo4j ? 'text' : 'password'} placeholder={t('organization:integrations.neo4j.passwordPlaceholder')}
                              className="w-full px-3 py-2 pr-8 border border-gray-200 rounded-sm text-sm focus:outline-none focus:ring-1 focus:ring-orange-500 bg-white"
                              value={integForm.neo4j_password} onChange={e => setIntegForm(p => ({ ...p, neo4j_password: e.target.value }))} />
                            <button type="button" onClick={() => setShowSecrets(p => ({ ...p, neo4j: !p.neo4j }))} className="absolute right-2 top-1/2 -translate-y-1/2 text-gray-400">
                              {showSecrets.neo4j ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
                            </button>
                          </div>
                        </div>
                      )}
                    </div>

                    {/* Notion */}
                    <div className="p-4 bg-gray-50 rounded-button space-y-3">
                      <div className="flex items-center justify-between">
                        <h3 className="font-semibold text-gray-800">{t('organization:integrations.notion.title')}</h3>
                        <span className={`text-xs font-medium px-2 py-0.5 rounded-full ${integrations?.notion?.configured ? 'bg-green-100 text-green-700' : 'bg-gray-100 text-gray-500'}`}>
                          {integrations?.notion?.configured ? t('organization:integrations.configured') : t('organization:integrations.notConfigured')}
                        </span>
                      </div>
                      {integrations?.notion?.configured ? (
                        <div className="flex items-center justify-between p-3 bg-white border border-green-200 rounded-sm">
                          <div>
                            <p className="text-sm text-gray-700">
                              <span className="font-medium">{t('organization:integrations.notion.apiKey')}:</span>{' '}
                              <code className="text-xs bg-gray-100 px-1.5 py-0.5 rounded">{integrations.notion.key_preview}</code>
                            </p>
                          </div>
                          <button onClick={() => handleDeleteIntegration('notion')} disabled={integLoading}
                            className="flex items-center space-x-1.5 px-3 py-1.5 text-red-600 hover:bg-red-50 border border-red-200 rounded-sm transition-colors text-sm disabled:opacity-50">
                            <Trash2 className="w-3.5 h-3.5" />
                            <span>{t('organization:integrations.removeButton')}</span>
                          </button>
                        </div>
                      ) : (
                        <div className="relative">
                          <input type={showSecrets.notion ? 'text' : 'password'} placeholder={t('organization:integrations.notion.apiKeyPlaceholder')}
                            className="w-full px-3 py-2 pr-8 border border-gray-200 rounded-sm text-sm focus:outline-none focus:ring-1 focus:ring-orange-500 bg-white"
                            value={integForm.notion_api_key} onChange={e => setIntegForm(p => ({ ...p, notion_api_key: e.target.value }))} />
                          <button type="button" onClick={() => setShowSecrets(p => ({ ...p, notion: !p.notion }))} className="absolute right-2 top-1/2 -translate-y-1/2 text-gray-400">
                            {showSecrets.notion ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
                          </button>
                        </div>
                      )}
                    </div>

                    {(!integrations?.neo4j?.configured || !integrations?.notion?.configured) && (
                      <button onClick={handleSaveIntegrations} disabled={integLoading}
                        className="px-6 py-3 bg-gradient-to-r from-orange-500 to-orange-600 hover:from-orange-600 hover:to-orange-700 text-white font-semibold rounded-button shadow-card hover:shadow-elevated disabled:opacity-50 disabled:cursor-not-allowed transition-all">
                        {integLoading ? <Loader2 className="w-5 h-5 animate-spin" /> : t('organization:integrations.saveButton')}
                      </button>
                    )}
                  </div>
                </div>
              )}

              {/* ---- Slash Commands (admin/owner) ---- */}
              {['admin', 'owner'].includes(company.role) && (
                <div className="bg-white rounded-card shadow-card border border-gray-200 p-8">
                  <button onClick={() => setSlashOpen(!slashOpen)} className="w-full flex items-center justify-between mb-4">
                    <div className="flex items-center space-x-3">
                      <div className="w-10 h-10 rounded-button bg-gradient-to-br from-purple-400 to-purple-600 flex items-center justify-center">
                        <Zap className="w-5 h-5 text-white" />
                      </div>
                      <div className="text-left">
                        <h2 className="text-xl font-heading font-bold text-gray-900">{t('organization:slashCommands.title')}</h2>
                        <p className="text-gray-500 text-sm">{t('organization:slashCommands.description')}</p>
                      </div>
                    </div>
                    {slashOpen ? <ChevronUp className="w-5 h-5 text-gray-400" /> : <ChevronDown className="w-5 h-5 text-gray-400" />}
                  </button>

                  {slashOpen && (
                    <div>
                      <div className="flex justify-end mb-4">
                        <button onClick={openSlashCreate}
                          className="px-4 py-2 bg-gradient-to-r from-purple-500 to-purple-600 hover:from-purple-600 hover:to-purple-700 text-white text-sm font-semibold rounded-button shadow-card transition-all">
                          + {t('organization:slashCommands.addButton')}
                        </button>
                      </div>

                      {slashCommands.length === 0 ? (
                        <p className="text-gray-400 text-sm text-center py-8">{t('organization:slashCommands.empty')}</p>
                      ) : (
                        <div className="overflow-x-auto">
                          <table className="w-full text-sm">
                            <thead>
                              <tr className="border-b border-gray-200 text-left">
                                <th className="pb-3 font-medium text-gray-500">{t('organization:slashCommands.table.command')}</th>
                                <th className="pb-3 font-medium text-gray-500">{t('organization:slashCommands.table.prompt')}</th>
                                <th className="pb-3 font-medium text-gray-500">{t('organization:slashCommands.table.companions')}</th>
                                <th className="pb-3 font-medium text-gray-500 w-24"></th>
                              </tr>
                            </thead>
                            <tbody>
                              {slashCommands.map(cmd => (
                                <tr key={cmd.id} className="border-b border-gray-100">
                                  <td className="py-3 pr-4">
                                    <code className="bg-purple-50 text-purple-700 px-2 py-1 rounded text-xs font-semibold">{cmd.command}</code>
                                  </td>
                                  <td className="py-3 pr-4 text-gray-600 max-w-xs truncate">{cmd.prompt}</td>
                                  <td className="py-3 pr-4">
                                    <div className="flex flex-wrap gap-1">
                                      {(cmd.agent_ids || []).map(aid => {
                                        const ag = orgAgents.find(a => a.id === aid);
                                        return ag ? (
                                          <span key={aid} className="bg-primary-50 text-primary-700 px-2 py-0.5 rounded-full text-xs">{ag.name}</span>
                                        ) : null;
                                      })}
                                    </div>
                                  </td>
                                  <td className="py-3 text-right">
                                    <button onClick={() => openSlashEdit(cmd)} className="text-gray-400 hover:text-purple-600 mr-2" title={t('organization:slashCommands.edit')}>
                                      <Edit3 className="w-4 h-4" />
                                    </button>
                                    <button onClick={() => handleDeleteSlashCommand(cmd.id)} className="text-gray-400 hover:text-red-600" title={t('organization:slashCommands.delete')}>
                                      <Trash2 className="w-4 h-4" />
                                    </button>
                                  </td>
                                </tr>
                              ))}
                            </tbody>
                          </table>
                        </div>
                      )}
                    </div>
                  )}
                </div>
              )}

              {/* ---- Org Agents (admin/owner) ---- */}
              {['admin', 'owner'].includes(company.role) && (
                <div className="bg-white rounded-card shadow-card border border-gray-200 p-8">
                  <button onClick={() => setAgentsOpen(!agentsOpen)} className="w-full flex items-center justify-between mb-4">
                    <div className="flex items-center space-x-3">
                      <div className="w-10 h-10 rounded-button bg-gradient-to-br from-green-400 to-green-600 flex items-center justify-center">
                        <Bot className="w-5 h-5 text-white" />
                      </div>
                      <h2 className="text-xl font-heading font-bold text-gray-900">{t('organization:agents.title')} ({orgAgents.length})</h2>
                    </div>
                    {agentsOpen ? <ChevronUp className="w-5 h-5 text-gray-400" /> : <ChevronDown className="w-5 h-5 text-gray-400" />}
                  </button>

                  {agentsOpen && (
                    orgAgents.length === 0 ? (
                      <p className="text-gray-500 text-sm">{t('organization:agents.noAgents')}</p>
                    ) : (
                      <div className="overflow-x-auto">
                        <table className="w-full text-sm">
                          <thead>
                            <tr className="border-b border-gray-200">
                              <th className="text-left py-3 px-2 font-semibold text-gray-600">{t('organization:agents.name')}</th>
                              <th className="text-left py-3 px-2 font-semibold text-gray-600">{t('organization:agents.type')}</th>
                              <th className="text-left py-3 px-2 font-semibold text-gray-600">{t('organization:agents.owner')}</th>
                              <th className="text-center py-3 px-2 font-semibold text-gray-600">{t('organization:agents.documents')}</th>
                              <th className="text-center py-3 px-2 font-semibold text-gray-600">{t('organization:agents.sharedWith')}</th>
                              <th className="text-right py-3 px-2 font-semibold text-gray-600">{t('organization:agents.actions')}</th>
                            </tr>
                          </thead>
                          <tbody>
                            {orgAgents.map(a => (
                              <tr key={a.id} className="border-b border-gray-100 hover:bg-gray-50/50 transition-colors">
                                <td className="py-3 px-2 font-medium text-gray-900">{a.name}</td>
                                <td className="py-3 px-2 text-gray-500 capitalize">{a.type}</td>
                                <td className="py-3 px-2 text-gray-500">{a.owner_username}</td>
                                <td className="py-3 px-2 text-center">
                                  <span className="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium bg-gray-100 text-gray-700">
                                    <FileText className="w-3 h-3 mr-1" />{a.document_count}
                                  </span>
                                </td>
                                <td className="py-3 px-2 text-center">
                                  <span className="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium bg-primary-50 text-primary-700">
                                    <Users className="w-3 h-3 mr-1" />{a.shared_with_count || 0}
                                  </span>
                                </td>
                                <td className="py-3 px-2 text-right">
                                  <div className="flex items-center justify-end space-x-1">
                                    <button onClick={() => openShareModal(a)} className="p-1.5 text-primary-500 hover:text-primary-700 hover:bg-primary-50 rounded-sm transition-colors" title={t('organization:agents.share')}>
                                      <Share2 className="w-4 h-4" />
                                    </button>
                                    <button onClick={() => handleDeleteOrgAgent(a.id)} className="p-1.5 text-red-400 hover:text-red-600 hover:bg-red-50 rounded-sm transition-colors" title={t('organization:agents.actions')}>
                                      <Trash2 className="w-4 h-4" />
                                    </button>
                                  </div>
                                </td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </div>
                    )
                  )}
                </div>
              )}
            </div>
          )}
        </div>
      </div>

      {/* ---- Share Modal ---- */}
      {shareModalAgent && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-sm" onClick={() => setShareModalAgent(null)}>
          <div className="bg-white rounded-card shadow-floating w-full max-w-md mx-4 p-6" onClick={e => e.stopPropagation()}>
            <div className="flex items-center justify-between mb-6">
              <h3 className="text-lg font-bold text-gray-900">{t('organization:agents.shareModal.title')} — {shareModalAgent.name}</h3>
              <button onClick={() => setShareModalAgent(null)} className="p-1 text-gray-400 hover:text-gray-600 rounded-sm hover:bg-gray-100 transition-colors">
                <X className="w-5 h-5" />
              </button>
            </div>

            {/* Share with a new member */}
            <div className="flex gap-2 mb-6">
              <select
                value={shareTargetUserId}
                onChange={e => setShareTargetUserId(e.target.value)}
                className="flex-1 px-3 py-2 border border-gray-200 rounded-input focus:border-primary-500 focus:ring-2 focus:ring-primary-100 transition-all outline-none bg-white text-sm"
              >
                <option value="">{t('organization:agents.shareModal.selectUser')}</option>
                {members
                  .filter(m => m.user_id !== shareModalAgent.owner_id && !agentShares.some(s => s.user_id === m.user_id))
                  .map(m => (
                    <option key={m.user_id} value={m.user_id}>{m.username} ({m.email})</option>
                  ))
                }
              </select>
              <button
                onClick={handleShare}
                disabled={!shareTargetUserId || shareLoading}
                className="px-4 py-2 bg-gradient-to-r from-primary-500 to-primary-600 hover:from-primary-600 hover:to-primary-700 text-white font-semibold rounded-button shadow-card hover:shadow-elevated disabled:opacity-50 disabled:cursor-not-allowed transition-all text-sm whitespace-nowrap"
              >
                {shareLoading ? <Loader2 className="w-4 h-4 animate-spin" /> : t('organization:agents.shareModal.shareButton')}
              </button>
            </div>
            <label className="flex items-center gap-2 mb-6 cursor-pointer select-none">
              <input
                type="checkbox"
                checked={shareCanEdit}
                onChange={e => setShareCanEdit(e.target.checked)}
                className="w-4 h-4 rounded border-gray-300 text-primary-600 focus:ring-primary-500"
              />
              <span className="text-sm text-gray-700">{t('organization:agents.shareModal.canEdit')}</span>
            </label>

            {/* Current shares */}
            <div>
              <h4 className="text-sm font-semibold text-gray-700 mb-3">{t('organization:agents.shareModal.currentShares')}</h4>
              {agentShares.length === 0 ? (
                <p className="text-sm text-gray-400">{t('organization:agents.shareModal.noShares')}</p>
              ) : (
                <div className="space-y-2 max-h-48 overflow-y-auto">
                  {agentShares.map(s => (
                    <div key={s.user_id} className="flex items-center justify-between p-2 bg-gray-50 rounded-sm">
                      <div>
                        <span className="text-sm font-medium text-gray-900">{s.username}</span>
                        <span className="text-xs text-gray-400 ml-2">{s.email}</span>
                      </div>
                      <div className="flex items-center gap-2">
                        <label className="flex items-center gap-1 cursor-pointer select-none">
                          <div
                            onClick={() => handleToggleCanEdit(s.user_id, s.can_edit)}
                            className={`relative inline-flex h-5 w-9 items-center rounded-full transition-colors ${s.can_edit ? 'bg-primary-600' : 'bg-gray-300'}`}
                          >
                            <span className={`inline-block h-3.5 w-3.5 transform rounded-full bg-white transition-transform ${s.can_edit ? 'translate-x-4' : 'translate-x-0.5'}`} />
                          </div>
                          <span className="text-xs text-gray-500">{t('organization:agents.shareModal.canEdit')}</span>
                        </label>
                        <button
                          onClick={() => handleRemoveShare(s.user_id)}
                          className="text-xs px-2 py-1 text-red-600 hover:bg-red-50 border border-red-200 rounded-sm transition-colors"
                        >
                          {t('organization:agents.shareModal.remove')}
                        </button>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>
        </div>
      )}

      {/* Slash Command Modal */}
      {slashModalOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-sm">
          <div className="bg-white rounded-card shadow-elevated w-full max-w-lg mx-4 p-6">
            <div className="flex items-center justify-between mb-6">
              <h3 className="text-lg font-heading font-bold text-gray-900">
                {slashEditItem ? t('organization:slashCommands.modal.editTitle') : t('organization:slashCommands.modal.createTitle')}
              </h3>
              <button onClick={() => setSlashModalOpen(false)} className="text-gray-400 hover:text-gray-600">
                <X className="w-5 h-5" />
              </button>
            </div>

            <div className="space-y-4">
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">{t('organization:slashCommands.modal.commandLabel')}</label>
                <div className="flex items-center border border-gray-200 rounded-sm overflow-hidden focus-within:ring-2 focus-within:ring-purple-500">
                  <span className="px-3 text-purple-600 font-bold bg-gray-50">/</span>
                  <input type="text" className="flex-1 px-3 py-2 text-sm outline-none"
                    placeholder={t('organization:slashCommands.modal.commandPlaceholder')}
                    value={slashForm.command}
                    onChange={e => setSlashForm(p => ({ ...p, command: e.target.value.replace(/[^a-zA-Z0-9_-]/g, '') }))} />
                </div>
              </div>

              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">{t('organization:slashCommands.modal.promptLabel')}</label>
                <textarea className="w-full px-3 py-2 border border-gray-200 rounded-sm text-sm focus:outline-none focus:ring-2 focus:ring-purple-500 resize-none"
                  rows={4}
                  placeholder={t('organization:slashCommands.modal.promptPlaceholder')}
                  value={slashForm.prompt}
                  onChange={e => setSlashForm(p => ({ ...p, prompt: e.target.value }))} />
              </div>

              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">{t('organization:slashCommands.modal.companionsLabel')}</label>
                <div className="border border-gray-200 rounded-sm p-2 min-h-[40px] flex flex-wrap gap-1 items-center">
                  {slashForm.agent_ids.map(aid => {
                    const ag = orgAgents.find(a => a.id === aid);
                    return ag ? (
                      <span key={aid} className="bg-primary-50 text-primary-700 px-2 py-0.5 rounded-full text-xs flex items-center gap-1">
                        {ag.name}
                        <button onClick={() => setSlashForm(p => ({ ...p, agent_ids: p.agent_ids.filter(x => x !== aid) }))}
                          className="text-primary-500 hover:text-red-500">
                          <X className="w-3 h-3" />
                        </button>
                      </span>
                    ) : null;
                  })}
                  <select
                    className="text-sm text-gray-500 bg-transparent outline-none cursor-pointer"
                    value=""
                    onChange={e => {
                      const id = parseInt(e.target.value);
                      if (id && !slashForm.agent_ids.includes(id)) {
                        setSlashForm(p => ({ ...p, agent_ids: [...p.agent_ids, id] }));
                      }
                    }}
                  >
                    <option value="">{t('organization:slashCommands.modal.addCompanion')}</option>
                    {orgAgents.filter(a => !slashForm.agent_ids.includes(a.id)).map(a => (
                      <option key={a.id} value={a.id}>{a.name}</option>
                    ))}
                  </select>
                </div>
              </div>
            </div>

            <div className="flex justify-end gap-3 mt-6">
              <button onClick={() => setSlashModalOpen(false)}
                className="px-4 py-2 border border-gray-200 rounded-sm text-sm text-gray-600 hover:bg-gray-50 transition-colors">
                {t('organization:slashCommands.modal.cancel')}
              </button>
              <button onClick={handleSaveSlashCommand} disabled={slashLoading}
                className="px-4 py-2 bg-gradient-to-r from-purple-500 to-purple-600 hover:from-purple-600 hover:to-purple-700 text-white text-sm font-semibold rounded-button shadow-card transition-all disabled:opacity-50">
                {slashLoading ? <Loader2 className="w-4 h-4 animate-spin" /> : t('organization:slashCommands.modal.save')}
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
      ...(await serverSideTranslations(locale, ['organization', 'common', 'errors'])),
    },
  };
}
