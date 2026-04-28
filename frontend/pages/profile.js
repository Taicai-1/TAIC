import { useState, useEffect } from 'react';
import { useRouter } from 'next/router';
import { useTranslation } from 'next-i18next';
import { serverSideTranslations } from 'next-i18next/serverSideTranslations';
import { useAuth } from '../hooks/useAuth';
import api from '../lib/api';

import toast, { Toaster } from 'react-hot-toast';
import dynamic from 'next/dynamic';
import {
  ArrowLeft,
  User,
  Mail,
  Calendar,
  Bot,
  FileText,
  MessageCircle,
  Zap,
  Download,
  Shield,
  AlertTriangle,
  Trash2,
  Loader2,
  Award,
  TrendingUp,
  Building2,
  CheckCircle,
  KeyRound,
  Lock,
  Eye,
  EyeOff,
  Activity,
  BarChart3,
  PieChart as PieChartIcon,
  MessageSquare
} from 'lucide-react';
import Layout from '../components/Layout';
import LanguageSwitcher from '../components/LanguageSwitcher';
import {
  AreaChart, Area, BarChart, Bar, PieChart, Pie, Cell,
  XAxis, YAxis, Tooltip, ResponsiveContainer, Legend
} from 'recharts';

export default function Profile() {
  const router = useRouter();
  const { t } = useTranslation(['profile', 'common', 'errors']);
  const { user: authUser, loading: authLoading, authenticated } = useAuth();
  const [user, setUser] = useState(null);
  const [stats, setStats] = useState(null);
  const [loading, setLoading] = useState(true);
  const [exportLoading, setExportLoading] = useState(false);
  const [deleteLoading, setDeleteLoading] = useState(false);
  const [showDeleteConfirm, setShowDeleteConfirm] = useState(false);
  const [company, setCompany] = useState(null);
  const [companyInput, setCompanyInput] = useState('');
  const [companyLoading, setCompanyLoading] = useState(false);
  const [twoFactorStatus, setTwoFactorStatus] = useState(null);
  const [passwordForm, setPasswordForm] = useState({ current: '', newPwd: '', confirm: '' });
  const [passwordLoading, setPasswordLoading] = useState(false);
  const [showPasswords, setShowPasswords] = useState({ current: false, newPwd: false, confirm: false });
  const [analytics, setAnalytics] = useState(null);
  const [analyticsLoading, setAnalyticsLoading] = useState(true);

  useEffect(() => {
    if (!authenticated) return;
    loadUserData();
    loadCompany();
    load2FAStatus();
    loadAnalytics();
  }, [authenticated]);

  const loadUserData = async () => {
    try {
      const res = await api.get('/api/user/export-data');
      setUser(res.data.user);
      setStats(res.data.statistics);
    } catch (error) {
      console.error('Error loading user data:', error);
      toast.error(t('errors:network.unknown'));
    } finally {
      setLoading(false);
    }
  };

  const loadCompany = async () => {
    try {
      const res = await api.get('/api/companies/mine');
      setCompany(res.data.company); // Now includes role, invite_code, etc.
    } catch (error) {
      // silent fail - company is optional
    }
  };

  const load2FAStatus = async () => {
    try {
      const res = await api.get('/auth/2fa/status');
      setTwoFactorStatus(res.data);
    } catch (error) {
      // silent fail
    }
  };

  const loadAnalytics = async () => {
    try {
      const res = await api.get('/api/user/stats');
      const data = res.data;
      // Fill missing dates for the last 30 days
      const today = new Date();
      const dateMap = {};
      (data.messages_per_day || []).forEach(d => { dateMap[d.date] = d.count; });
      const filled = [];
      for (let i = 29; i >= 0; i--) {
        const d = new Date(today);
        d.setDate(d.getDate() - i);
        const key = d.toISOString().split('T')[0];
        filled.push({ date: key, count: dateMap[key] || 0 });
      }
      data.messages_per_day = filled;
      setAnalytics(data);
    } catch (error) {
      // silent fail - analytics is optional
    } finally {
      setAnalyticsLoading(false);
    }
  };

  const handleCreateCompany = async () => {
    if (!companyInput.trim()) return;
    setCompanyLoading(true);
    try {
      const res = await api.post('/api/companies', { name: companyInput.trim() });
      setCompany(res.data.company);
      setCompanyInput('');
      toast.success(t('profile:company.created'));
    } catch (error) {
      toast.error(error.response?.data?.detail || t('profile:company.error'));
    } finally {
      setCompanyLoading(false);
    }
  };

  const handleJoinCompany = async () => {
    if (!companyInput.trim()) return;
    setCompanyLoading(true);
    try {
      const res = await api.put('/api/user/company', { company_name: companyInput.trim() });
      setCompany(res.data.company);
      setCompanyInput('');
      toast.success(t('profile:company.joined'));
    } catch (error) {
      toast.error(error.response?.data?.detail || t('profile:company.notFound'));
    } finally {
      setCompanyLoading(false);
    }
  };

  const handleExportData = async () => {
    setExportLoading(true);
    try {
      const res = await api.get('/api/user/export-data');
      const blob = new Blob([JSON.stringify(res.data, null, 2)], { type: 'application/json' });
      const url = window.URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `taic-data-export-${new Date().toISOString().split('T')[0]}.json`;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      window.URL.revokeObjectURL(url);

      toast.success(t('profile:alerts.exportSuccess'));
    } catch (error) {
      console.error('Error exporting data:', error);
      toast.error(t('profile:alerts.exportError'));
    } finally {
      setExportLoading(false);
    }
  };

  const handleDeleteAccount = async () => {
    setDeleteLoading(true);
    try {
      await api.delete('/api/user/delete-account?anonymize=false');
      await api.post('/logout', {});
      toast.success(t('profile:alerts.deleteSuccess'));
      setTimeout(() => router.push('/login'), 2000);
    } catch (error) {
      console.error('Error deleting account:', error);
      toast.error(t('profile:alerts.deleteError'));
    } finally {
      setDeleteLoading(false);
      setShowDeleteConfirm(false);
    }
  };

  const passwordValid = {
    length: passwordForm.newPwd.length >= 8,
    uppercase: /[A-Z]/.test(passwordForm.newPwd),
    lowercase: /[a-z]/.test(passwordForm.newPwd),
    digit: /[0-9]/.test(passwordForm.newPwd),
  };
  const allPasswordValid = Object.values(passwordValid).every(Boolean);
  const passwordsMatch = passwordForm.newPwd && passwordForm.newPwd === passwordForm.confirm;

  const handleChangePassword = async () => {
    if (!allPasswordValid || !passwordsMatch) return;
    if (passwordForm.current === passwordForm.newPwd) {
      toast.error(t('profile:changePassword.errorSamePassword'));
      return;
    }
    setPasswordLoading(true);
    try {
      await api.post('/api/user/change-password', {
        current_password: passwordForm.current,
        new_password: passwordForm.newPwd
      });
      toast.success(t('profile:changePassword.success'));
      setPasswordForm({ current: '', newPwd: '', confirm: '' });
      setShowPasswords({ current: false, newPwd: false, confirm: false });
    } catch (error) {
      if (error.response?.status === 429) {
        toast.error(t('profile:changePassword.errorRateLimit'));
      } else if (error.response?.status === 401) {
        toast.error(t('profile:changePassword.errorIncorrect'));
      } else {
        toast.error(error.response?.data?.detail || t('profile:changePassword.errorGeneric'));
      }
    } finally {
      setPasswordLoading(false);
    }
  };

  if (authLoading || loading) {
    return (
      <div className="min-h-screen bg-gray-50 flex items-center justify-center">
        <div className="flex flex-col items-center space-y-4">
          <Loader2 className="w-12 h-12 text-blue-600 animate-spin" />
          <p className="text-xl font-semibold text-gray-700">{t('profile:loading')}</p>
        </div>
      </div>
    );
  }

  return (
    <Layout showBack backHref="/agents" title={t('profile:title')}>
      <Toaster position="top-right" />

      <div className="py-8 px-4 sm:px-6 lg:px-8">
        <div className="max-w-6xl mx-auto">

          {/* Profile Header Card */}
          <div className="bg-white rounded-card shadow-card border border-gray-200 p-8 mb-8 animate-fade-in">
            <div className="flex flex-col sm:flex-row items-center sm:items-start gap-6">
              {/* Avatar */}
              <div className="relative">
                <div className="w-24 h-24 rounded-full bg-gradient-to-br from-blue-500 via-purple-500 to-pink-500 flex items-center justify-center shadow-elevated">
                  <User className="w-12 h-12 text-white" />
                </div>
                <div className="absolute -bottom-2 -right-2 w-8 h-8 bg-green-500 rounded-full border-4 border-white flex items-center justify-center shadow-subtle">
                  <CheckCircle className="w-4 h-4 text-white" />
                </div>
              </div>

              {/* User Info */}
              <div className="flex-1 text-center sm:text-left">
                <h1 className="text-3xl sm:text-4xl font-heading font-bold text-gray-900 mb-2">
                  {user?.username || 'User'}
                </h1>
                <div className="flex flex-col sm:flex-row items-center gap-4 text-gray-600 mb-4">
                  <div className="flex items-center space-x-2">
                    <Mail className="w-4 h-4" />
                    <span className="text-sm">{user?.email}</span>
                  </div>
                  <div className="flex items-center space-x-2">
                    <Calendar className="w-4 h-4" />
                    <span className="text-sm">
                      {t('profile:sections.accountInfo.memberSince')}: {user?.created_at ? new Date(user.created_at).toLocaleDateString(router.locale === 'fr' ? 'fr-FR' : 'en-US', { month: 'short', year: 'numeric' }) : 'N/A'}
                    </span>
                  </div>
                </div>
                <div className="flex flex-wrap justify-center sm:justify-start items-center gap-2">
                  <span className="inline-flex items-center px-3 py-1 rounded-full text-xs font-medium bg-blue-100 text-blue-700">
                    <Award className="w-3 h-3 mr-1" />
                    Active Member
                  </span>
                  <span className="inline-flex items-center px-3 py-1 rounded-full text-xs font-medium bg-purple-100 text-purple-700">
                    <TrendingUp className="w-3 h-3 mr-1" />
                    Pro User
                  </span>
                  <LanguageSwitcher />
                </div>
              </div>
            </div>
          </div>

          {/* Organization Card */}
          <div className="bg-white rounded-card shadow-card border border-gray-200 p-8 mb-8 animate-fade-in">
            <div className="flex items-start space-x-4 mb-6">
              <div className="w-12 h-12 rounded-button bg-gradient-to-br from-teal-400 to-teal-600 flex items-center justify-center shadow-card flex-shrink-0">
                <Building2 className="w-6 h-6 text-white" />
              </div>
              <div className="flex-1">
                <h2 className="text-2xl font-heading font-bold text-gray-900 mb-2">{t('profile:company.title')}</h2>
                <p className="text-gray-600">{t('profile:company.description')}</p>
              </div>
            </div>

            {company ? (
              <div className="flex items-center justify-between p-4 bg-teal-50 border border-teal-200 rounded-button">
                <div className="flex items-center space-x-3">
                  <Building2 className="w-5 h-5 text-teal-600" />
                  <span className="font-semibold text-teal-800">{company.name}</span>
                  {company.role && (
                    <span className="px-2 py-0.5 bg-teal-600 text-white text-xs font-medium rounded-full capitalize">{company.role}</span>
                  )}
                </div>
                <button
                  onClick={() => router.push('/organization')}
                  className="px-4 py-2 bg-teal-600 hover:bg-teal-700 text-white text-sm font-medium rounded-button transition-colors"
                >
                  {t('profile:company.manage')}
                </button>
              </div>
            ) : (
              <button
                onClick={() => router.push('/organization')}
                className="w-full px-4 py-3 bg-gradient-to-r from-teal-500 to-teal-600 hover:from-teal-600 hover:to-teal-700 text-white font-semibold rounded-button shadow-card transition-all"
              >
                {t('profile:company.joinOrCreate')}
              </button>
            )}
          </div>

          {/* 2FA Security Card */}
          {twoFactorStatus && (
            <div className="bg-white rounded-card shadow-card border border-gray-200 p-8 mb-8 animate-fade-in">
              <div className="flex items-start space-x-4 mb-6">
                <div className="w-12 h-12 rounded-button bg-gradient-to-br from-blue-400 to-purple-600 flex items-center justify-center shadow-card flex-shrink-0">
                  <Shield className="w-6 h-6 text-white" />
                </div>
                <div className="flex-1">
                  <h2 className="text-2xl font-heading font-bold text-gray-900 mb-2">{t('profile:twoFactor.title')}</h2>
                  <p className="text-gray-600">{t('profile:twoFactor.description')}</p>
                </div>
              </div>

              <div className="space-y-4">
                {/* Status */}
                <div className="flex items-center space-x-3 p-4 bg-green-50 border border-green-200 rounded-button">
                  <CheckCircle className="w-5 h-5 text-green-600" />
                  <span className="font-semibold text-green-800">{t('profile:twoFactor.enabled')}</span>
                </div>

                {/* Activated date */}
                {twoFactorStatus.setup_completed_at && (
                  <div className="p-4 bg-gray-50 rounded-button">
                    <div className="flex items-center space-x-2 mb-1">
                      <Calendar className="w-4 h-4 text-gray-500" />
                      <span className="text-sm font-medium text-gray-600">{t('profile:twoFactor.activatedOn')}</span>
                    </div>
                    <span className="text-sm text-gray-800">
                      {new Date(twoFactorStatus.setup_completed_at).toLocaleDateString(router.locale === 'fr' ? 'fr-FR' : 'en-US', { day: 'numeric', month: 'long', year: 'numeric' })}
                    </span>
                  </div>
                )}
              </div>
            </div>
          )}

          {/* Change Password Card */}
          <div className="bg-white rounded-card shadow-card border border-gray-200 p-8 mb-8 animate-fade-in">
            <div className="flex items-start space-x-4 mb-6">
              <div className="w-12 h-12 rounded-button bg-gradient-to-br from-orange-400 to-orange-600 flex items-center justify-center shadow-card flex-shrink-0">
                <KeyRound className="w-6 h-6 text-white" />
              </div>
              <div className="flex-1">
                <h2 className="text-2xl font-heading font-bold text-gray-900 mb-2">{t('profile:changePassword.title')}</h2>
                <p className="text-gray-600">{t('profile:changePassword.description')}</p>
              </div>
            </div>

            <div className="space-y-4 max-w-md">
              {/* Current password */}
              <div className="relative">
                <Lock className="absolute left-3 top-1/2 -translate-y-1/2 w-5 h-5 text-gray-400" />
                <input
                  type={showPasswords.current ? 'text' : 'password'}
                  className="w-full pl-10 pr-10 py-3 border border-gray-200 rounded-input focus:border-orange-500 focus:ring-2 focus:ring-orange-200 transition-all outline-none bg-white"
                  placeholder={t('profile:changePassword.currentPassword')}
                  value={passwordForm.current}
                  onChange={e => setPasswordForm(prev => ({ ...prev, current: e.target.value }))}
                />
                <button type="button" onClick={() => setShowPasswords(prev => ({ ...prev, current: !prev.current }))} className="absolute right-3 top-1/2 -translate-y-1/2 text-gray-400 hover:text-gray-600">
                  {showPasswords.current ? <EyeOff className="w-5 h-5" /> : <Eye className="w-5 h-5" />}
                </button>
              </div>

              {/* New password */}
              <div className="relative">
                <Lock className="absolute left-3 top-1/2 -translate-y-1/2 w-5 h-5 text-gray-400" />
                <input
                  type={showPasswords.newPwd ? 'text' : 'password'}
                  className="w-full pl-10 pr-10 py-3 border border-gray-200 rounded-input focus:border-orange-500 focus:ring-2 focus:ring-orange-200 transition-all outline-none bg-white"
                  placeholder={t('profile:changePassword.newPassword')}
                  value={passwordForm.newPwd}
                  onChange={e => setPasswordForm(prev => ({ ...prev, newPwd: e.target.value }))}
                />
                <button type="button" onClick={() => setShowPasswords(prev => ({ ...prev, newPwd: !prev.newPwd }))} className="absolute right-3 top-1/2 -translate-y-1/2 text-gray-400 hover:text-gray-600">
                  {showPasswords.newPwd ? <EyeOff className="w-5 h-5" /> : <Eye className="w-5 h-5" />}
                </button>
              </div>

              {/* Password requirements */}
              {passwordForm.newPwd && (
                <div className="grid grid-cols-2 gap-2 text-sm">
                  <div className={`flex items-center space-x-1.5 ${passwordValid.length ? 'text-green-600' : 'text-gray-400'}`}>
                    <span>{passwordValid.length ? '\u2713' : '\u2717'}</span>
                    <span>{t('profile:changePassword.requirements.length')}</span>
                  </div>
                  <div className={`flex items-center space-x-1.5 ${passwordValid.uppercase ? 'text-green-600' : 'text-gray-400'}`}>
                    <span>{passwordValid.uppercase ? '\u2713' : '\u2717'}</span>
                    <span>{t('profile:changePassword.requirements.uppercase')}</span>
                  </div>
                  <div className={`flex items-center space-x-1.5 ${passwordValid.lowercase ? 'text-green-600' : 'text-gray-400'}`}>
                    <span>{passwordValid.lowercase ? '\u2713' : '\u2717'}</span>
                    <span>{t('profile:changePassword.requirements.lowercase')}</span>
                  </div>
                  <div className={`flex items-center space-x-1.5 ${passwordValid.digit ? 'text-green-600' : 'text-gray-400'}`}>
                    <span>{passwordValid.digit ? '\u2713' : '\u2717'}</span>
                    <span>{t('profile:changePassword.requirements.digit')}</span>
                  </div>
                </div>
              )}

              {/* Confirm new password */}
              <div className="relative">
                <Lock className="absolute left-3 top-1/2 -translate-y-1/2 w-5 h-5 text-gray-400" />
                <input
                  type={showPasswords.confirm ? 'text' : 'password'}
                  className={`w-full pl-10 pr-10 py-3 border-2 rounded-input focus:ring-2 transition-all outline-none bg-white ${
                    passwordForm.confirm
                      ? passwordsMatch
                        ? 'border-green-400 focus:border-green-500 focus:ring-green-200'
                        : 'border-red-400 focus:border-red-500 focus:ring-red-200'
                      : 'border-gray-200 focus:border-orange-500 focus:ring-orange-200'
                  }`}
                  placeholder={t('profile:changePassword.confirmPassword')}
                  value={passwordForm.confirm}
                  onChange={e => setPasswordForm(prev => ({ ...prev, confirm: e.target.value }))}
                />
                <button type="button" onClick={() => setShowPasswords(prev => ({ ...prev, confirm: !prev.confirm }))} className="absolute right-3 top-1/2 -translate-y-1/2 text-gray-400 hover:text-gray-600">
                  {showPasswords.confirm ? <EyeOff className="w-5 h-5" /> : <Eye className="w-5 h-5" />}
                </button>
              </div>

              {passwordForm.confirm && !passwordsMatch && (
                <p className="text-sm text-red-500">{t('profile:changePassword.errorMismatch')}</p>
              )}

              <button
                onClick={handleChangePassword}
                disabled={passwordLoading || !passwordForm.current || !allPasswordValid || !passwordsMatch}
                className="w-full flex items-center justify-center space-x-2 px-6 py-3 bg-gradient-to-r from-orange-500 to-orange-600 hover:from-orange-600 hover:to-orange-700 text-white rounded-button font-semibold shadow-card hover:shadow-elevated disabled:opacity-50 disabled:cursor-not-allowed transition-all duration-300"
              >
                {passwordLoading ? (
                  <>
                    <Loader2 className="w-5 h-5 animate-spin" />
                    <span>{t('profile:changePassword.submitting')}</span>
                  </>
                ) : (
                  <>
                    <KeyRound className="w-5 h-5" />
                    <span>{t('profile:changePassword.submit')}</span>
                  </>
                )}
              </button>
            </div>
          </div>

          {/* Statistics Grid */}
          {stats && (
            <div className="grid grid-cols-2 lg:grid-cols-4 gap-4 sm:gap-6 mb-8">
              <div className="group bg-white/90 backdrop-blur-sm rounded-card shadow-elevated border-2 border-white/50 p-6 hover:shadow-elevated transition-all duration-200 animate-fade-in">
                <div className="flex items-center justify-between mb-3">
                  <div className="w-12 h-12 rounded-button bg-gradient-to-br from-blue-400 to-blue-600 flex items-center justify-center shadow-card group-hover:scale-110 transition-transform">
                    <Bot className="w-6 h-6 text-white" />
                  </div>
                </div>
                <div className="text-3xl font-bold text-gray-900 mb-1">{stats.total_agents}</div>
                <div className="text-sm font-medium text-gray-600">{t('profile:sections.statistics.agents')}</div>
              </div>

              <div className="group bg-white/90 backdrop-blur-sm rounded-card shadow-elevated border-2 border-white/50 p-6 hover:shadow-elevated transition-all duration-200 animate-fade-in animation-delay-100">
                <div className="flex items-center justify-between mb-3">
                  <div className="w-12 h-12 rounded-button bg-gradient-to-br from-green-400 to-green-600 flex items-center justify-center shadow-card group-hover:scale-110 transition-transform">
                    <FileText className="w-6 h-6 text-white" />
                  </div>
                </div>
                <div className="text-3xl font-bold text-gray-900 mb-1">{stats.total_documents}</div>
                <div className="text-sm font-medium text-gray-600">{t('profile:sections.statistics.documents')}</div>
              </div>

              <div className="group bg-white/90 backdrop-blur-sm rounded-card shadow-elevated border-2 border-white/50 p-6 hover:shadow-elevated transition-all duration-200 animate-fade-in animation-delay-200">
                <div className="flex items-center justify-between mb-3">
                  <div className="w-12 h-12 rounded-button bg-gradient-to-br from-purple-400 to-purple-600 flex items-center justify-center shadow-card group-hover:scale-110 transition-transform">
                    <MessageCircle className="w-6 h-6 text-white" />
                  </div>
                </div>
                <div className="text-3xl font-bold text-gray-900 mb-1">{stats.total_conversations}</div>
                <div className="text-sm font-medium text-gray-600">{t('profile:sections.statistics.conversations')}</div>
              </div>

              <div className="group bg-white/90 backdrop-blur-sm rounded-card shadow-elevated border-2 border-white/50 p-6 hover:shadow-elevated transition-all duration-200 animate-fade-in animation-delay-300">
                <div className="flex items-center justify-between mb-3">
                  <div className="w-12 h-12 rounded-button bg-gradient-to-br from-orange-400 to-orange-600 flex items-center justify-center shadow-card group-hover:scale-110 transition-transform">
                    <Zap className="w-6 h-6 text-white" />
                  </div>
                </div>
                <div className="text-3xl font-bold text-gray-900 mb-1">{stats.total_messages}</div>
                <div className="text-sm font-medium text-gray-600">{t('profile:sections.statistics.messages')}</div>
              </div>
            </div>
          )}

          {/* Analytics Section */}
          <div className="bg-white rounded-card shadow-card border border-gray-200 p-8 mb-8 animate-fade-in">
            <div className="flex items-start space-x-4 mb-6">
              <div className="w-12 h-12 rounded-button bg-gradient-to-br from-indigo-400 via-purple-500 to-pink-500 flex items-center justify-center shadow-card flex-shrink-0">
                <Activity className="w-6 h-6 text-white" />
              </div>
              <div className="flex-1">
                <h2 className="text-2xl font-heading font-bold text-gray-900 mb-1">{t('profile:sections.analytics.title')}</h2>
                <p className="text-gray-600">{t('profile:sections.analytics.description')}</p>
              </div>
            </div>

            {analyticsLoading ? (
              <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
                {[...Array(4)].map((_, i) => (
                  <div key={i} className={`animate-pulse bg-gray-200 rounded-button h-64 ${i === 0 ? 'lg:col-span-2' : ''}`} />
                ))}
              </div>
            ) : !analytics || (analytics.messages_per_day.every(d => d.count === 0) && analytics.messages_per_agent.length === 0) ? (
              <div className="text-center py-12">
                <Activity className="w-12 h-12 text-gray-300 mx-auto mb-4" />
                <p className="text-gray-500">{t('profile:sections.analytics.empty')}</p>
              </div>
            ) : (
              <div className="space-y-6">
                {/* Row 1: Activity over time (full width) */}
                <div className="bg-white rounded-card border border-gray-100 p-5">
                  <h3 className="text-sm font-semibold text-gray-700 mb-4 flex items-center gap-2">
                    <TrendingUp className="w-4 h-4 text-indigo-500" />
                    {t('profile:sections.analytics.activityOverTime')}
                  </h3>
                  <ResponsiveContainer width="100%" height={220}>
                    <AreaChart data={analytics.messages_per_day}>
                      <defs>
                        <linearGradient id="colorMessages" x1="0" y1="0" x2="0" y2="1">
                          <stop offset="5%" stopColor="#818cf8" stopOpacity={0.3} />
                          <stop offset="95%" stopColor="#c084fc" stopOpacity={0.05} />
                        </linearGradient>
                      </defs>
                      <XAxis
                        dataKey="date"
                        tickFormatter={(v) => { const d = new Date(v); return `${String(d.getDate()).padStart(2,'0')}/${String(d.getMonth()+1).padStart(2,'0')}`; }}
                        tick={{ fontSize: 11, fill: '#9ca3af' }}
                        axisLine={false}
                        tickLine={false}
                        interval="preserveStartEnd"
                      />
                      <YAxis tick={{ fontSize: 11, fill: '#9ca3af' }} axisLine={false} tickLine={false} allowDecimals={false} />
                      <Tooltip
                        contentStyle={{ background: '#fff', border: '1px solid #e5e7eb', borderRadius: '12px', fontSize: '13px' }}
                        labelFormatter={(v) => new Date(v).toLocaleDateString()}
                      />
                      <Area type="monotone" dataKey="count" stroke="#818cf8" strokeWidth={2} fill="url(#colorMessages)" name={t('profile:sections.analytics.messages')} />
                    </AreaChart>
                  </ResponsiveContainer>
                </div>

                {/* Row 2: Messages per agent + Feedback */}
                <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
                  <div className="bg-white rounded-card border border-gray-100 p-5">
                    <h3 className="text-sm font-semibold text-gray-700 mb-4 flex items-center gap-2">
                      <BarChart3 className="w-4 h-4 text-violet-500" />
                      {t('profile:sections.analytics.messagesPerAgent')}
                    </h3>
                    {analytics.messages_per_agent.length > 0 ? (
                      <ResponsiveContainer width="100%" height={200}>
                        <BarChart data={analytics.messages_per_agent.slice(0, 5)} layout="vertical">
                          <XAxis type="number" tick={{ fontSize: 11, fill: '#9ca3af' }} axisLine={false} tickLine={false} allowDecimals={false} />
                          <YAxis type="category" dataKey="name" tick={{ fontSize: 12, fill: '#6b7280' }} axisLine={false} tickLine={false} width={100} />
                          <Tooltip contentStyle={{ background: '#fff', border: '1px solid #e5e7eb', borderRadius: '12px', fontSize: '13px' }} />
                          <Bar dataKey="messages" fill="#8b5cf6" radius={[0, 6, 6, 0]} name={t('profile:sections.analytics.messages')} />
                        </BarChart>
                      </ResponsiveContainer>
                    ) : (
                      <div className="flex items-center justify-center h-[200px] text-gray-400 text-sm">{t('profile:sections.analytics.empty')}</div>
                    )}
                  </div>

                  <div className="bg-white rounded-card border border-gray-100 p-5">
                    <h3 className="text-sm font-semibold text-gray-700 mb-4 flex items-center gap-2">
                      <PieChartIcon className="w-4 h-4 text-emerald-500" />
                      {t('profile:sections.analytics.feedbackDistribution')}
                    </h3>
                    {(analytics.feedback.like + analytics.feedback.dislike + analytics.feedback.none) > 0 ? (
                      <ResponsiveContainer width="100%" height={200}>
                        <PieChart>
                          <Pie
                            data={[
                              { name: t('profile:sections.analytics.feedback.like'), value: analytics.feedback.like },
                              { name: t('profile:sections.analytics.feedback.dislike'), value: analytics.feedback.dislike },
                              { name: t('profile:sections.analytics.feedback.none'), value: analytics.feedback.none }
                            ]}
                            cx="50%" cy="50%" innerRadius={50} outerRadius={75} paddingAngle={3} dataKey="value"
                          >
                            <Cell fill="#10b981" />
                            <Cell fill="#ef4444" />
                            <Cell fill="#d1d5db" />
                          </Pie>
                          <Tooltip contentStyle={{ background: '#fff', border: '1px solid #e5e7eb', borderRadius: '12px', fontSize: '13px' }} />
                          <Legend iconType="circle" wrapperStyle={{ fontSize: '12px' }} />
                        </PieChart>
                      </ResponsiveContainer>
                    ) : (
                      <div className="flex items-center justify-center h-[200px] text-gray-400 text-sm">{t('profile:sections.analytics.empty')}</div>
                    )}
                  </div>
                </div>

                {/* Row 3: Conversations per agent + Role distribution */}
                <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
                  <div className="bg-white rounded-card border border-gray-100 p-5">
                    <h3 className="text-sm font-semibold text-gray-700 mb-4 flex items-center gap-2">
                      <MessageSquare className="w-4 h-4 text-indigo-500" />
                      {t('profile:sections.analytics.conversationsPerAgent')}
                    </h3>
                    {analytics.conversations_per_agent.length > 0 ? (
                      <ResponsiveContainer width="100%" height={200}>
                        <BarChart data={analytics.conversations_per_agent.slice(0, 5)}>
                          <XAxis dataKey="name" tick={{ fontSize: 11, fill: '#6b7280' }} axisLine={false} tickLine={false} />
                          <YAxis tick={{ fontSize: 11, fill: '#9ca3af' }} axisLine={false} tickLine={false} allowDecimals={false} />
                          <Tooltip contentStyle={{ background: '#fff', border: '1px solid #e5e7eb', borderRadius: '12px', fontSize: '13px' }} />
                          <Bar dataKey="conversations" fill="#6366f1" radius={[6, 6, 0, 0]} name={t('profile:sections.analytics.conversations')} />
                        </BarChart>
                      </ResponsiveContainer>
                    ) : (
                      <div className="flex items-center justify-center h-[200px] text-gray-400 text-sm">{t('profile:sections.analytics.empty')}</div>
                    )}
                  </div>

                  <div className="bg-white rounded-card border border-gray-100 p-5">
                    <h3 className="text-sm font-semibold text-gray-700 mb-4 flex items-center gap-2">
                      <PieChartIcon className="w-4 h-4 text-blue-500" />
                      {t('profile:sections.analytics.userVsAgent')}
                    </h3>
                    {(analytics.role_distribution.user + analytics.role_distribution.agent) > 0 ? (
                      <ResponsiveContainer width="100%" height={200}>
                        <PieChart>
                          <Pie
                            data={[
                              { name: t('profile:sections.analytics.roles.user'), value: analytics.role_distribution.user },
                              { name: t('profile:sections.analytics.roles.agent'), value: analytics.role_distribution.agent }
                            ]}
                            cx="50%" cy="50%" innerRadius={50} outerRadius={75} paddingAngle={3} dataKey="value"
                          >
                            <Cell fill="#3b82f6" />
                            <Cell fill="#a855f7" />
                          </Pie>
                          <Tooltip contentStyle={{ background: '#fff', border: '1px solid #e5e7eb', borderRadius: '12px', fontSize: '13px' }} />
                          <Legend iconType="circle" wrapperStyle={{ fontSize: '12px' }} />
                        </PieChart>
                      </ResponsiveContainer>
                    ) : (
                      <div className="flex items-center justify-center h-[200px] text-gray-400 text-sm">{t('profile:sections.analytics.empty')}</div>
                    )}
                  </div>
                </div>

                {/* Row 4: Mini stat cards */}
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                  <div className="bg-white rounded-card border border-gray-100 p-5 flex items-center space-x-4">
                    <div className="w-10 h-10 rounded-button bg-gradient-to-br from-amber-400 to-orange-500 flex items-center justify-center flex-shrink-0">
                      <MessageCircle className="w-5 h-5 text-white" />
                    </div>
                    <div>
                      <div className="text-2xl font-bold text-gray-900">{analytics.avg_messages_per_conversation}</div>
                      <div className="text-xs text-gray-500">{t('profile:sections.analytics.avgMessagesPerConversation')}</div>
                    </div>
                  </div>
                  <div className="bg-white rounded-card border border-gray-100 p-5 flex items-center space-x-4">
                    <div className="w-10 h-10 rounded-button bg-gradient-to-br from-violet-400 to-purple-600 flex items-center justify-center flex-shrink-0">
                      <Award className="w-5 h-5 text-white" />
                    </div>
                    <div>
                      <div className="text-2xl font-bold text-gray-900">{analytics.most_active_agent || '—'}</div>
                      <div className="text-xs text-gray-500">{t('profile:sections.analytics.mostActiveAgent')}</div>
                    </div>
                  </div>
                </div>
              </div>
            )}
          </div>

          {/* GDPR Data Export Card */}
          <div className="bg-white rounded-card shadow-card border border-gray-200 p-8 mb-8 animate-fade-in animation-delay-400">
            <div className="flex items-start space-x-4 mb-6">
              <div className="w-12 h-12 rounded-button bg-gradient-to-br from-indigo-400 to-indigo-600 flex items-center justify-center shadow-card flex-shrink-0">
                <Shield className="w-6 h-6 text-white" />
              </div>
              <div className="flex-1">
                <h2 className="text-2xl font-heading font-bold text-gray-900 mb-2">{t('profile:sections.gdpr.title')}</h2>
                <p className="text-gray-600">
                  {t('profile:sections.gdpr.description')}
                </p>
              </div>
            </div>
            <button
              onClick={handleExportData}
              disabled={exportLoading}
              className="group w-full sm:w-auto flex items-center justify-center space-x-3 px-6 py-4 bg-gradient-to-r from-indigo-500 to-indigo-600 hover:from-indigo-600 hover:to-indigo-700 text-white rounded-button shadow-card hover:shadow-elevated disabled:opacity-50 disabled:cursor-not-allowed transition-all"
            >
              {exportLoading ? (
                <>
                  <Loader2 className="w-5 h-5 animate-spin" />
                  <span className="font-semibold">{t('profile:sections.gdpr.exportButton.loading')}</span>
                </>
              ) : (
                <>
                  <Download className="w-5 h-5 group-hover:animate-bounce" />
                  <span className="font-semibold">{t('profile:sections.gdpr.exportButton.idle')}</span>
                </>
              )}
            </button>
            <p className="text-xs text-gray-500 mt-3 flex items-center">
              <FileText className="w-3 h-3 mr-1" />
              {t('profile:sections.gdpr.formatInfo')}
            </p>
          </div>

          {/* Danger Zone */}
          <div className="bg-white rounded-card shadow-card border border-red-200 p-8 animate-fade-in">
            <div className="border-b border-gray-200 pb-4 mb-6">
              <div className="flex items-center space-x-3 mb-2">
                <AlertTriangle className="w-6 h-6 text-red-600" />
                <h2 className="text-2xl font-heading font-bold text-gray-900">{t('profile:sections.dangerZone.title')}</h2>
              </div>
              <p className="text-sm text-gray-600">
                {t('profile:sections.dangerZone.description')}
              </p>
            </div>

            {/* Delete Account Section */}
            <div className="border border-red-200 rounded-button p-5 bg-red-50/50">
              <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
                <div className="flex-1">
                  <div className="flex items-center space-x-2 mb-2">
                    <Trash2 className="w-5 h-5 text-red-600" />
                    <h3 className="text-lg font-semibold text-gray-900">
                      {t('profile:sections.dangerZone.delete.button')}
                    </h3>
                  </div>
                  <p className="text-sm text-gray-600 mb-2">
                    {t('profile:sections.dangerZone.delete.description')}
                  </p>
                  <div className="flex items-start space-x-2 text-xs text-red-700 bg-red-100 border border-red-200 rounded-sm p-3">
                    <AlertTriangle className="w-4 h-4 mt-0.5 flex-shrink-0" />
                    <div>
                      <p className="font-semibold mb-1">This action cannot be undone.</p>
                      <p>All data including agents, documents, and conversations will be permanently deleted.</p>
                    </div>
                  </div>
                </div>
                <button
                  onClick={() => setShowDeleteConfirm(true)}
                  disabled={deleteLoading}
                  className="sm:flex-shrink-0 px-5 py-2.5 bg-red-600 hover:bg-red-700 text-white rounded-sm font-medium transition-colors disabled:opacity-50 disabled:cursor-not-allowed shadow-sm"
                >
                  Delete Account
                </button>
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* Delete Confirmation Modal */}
      {showDeleteConfirm && (
        <div className="fixed inset-0 bg-black/60 backdrop-blur-sm flex items-center justify-center p-4 z-50 animate-fade-in">
          <div className="bg-white rounded-card shadow-floating max-w-lg w-full animate-scale-in">
            {/* Modal Header */}
            <div className="px-6 py-5 border-b border-red-200 bg-red-50">
              <div className="flex items-center space-x-3">
                <div className="w-10 h-10 rounded-sm flex items-center justify-center bg-red-100">
                  <AlertTriangle className="w-6 h-6 text-red-600" />
                </div>
                <h3 className="text-xl font-bold text-gray-900">
                  {t('profile:modal.delete.title')}
                </h3>
              </div>
            </div>

            {/* Modal Body */}
            <div className="px-6 py-5">
              <p className="text-gray-700 mb-4 leading-relaxed">
                {t('profile:modal.delete.description')}
              </p>

              <div className="bg-red-50 border border-red-200 rounded-sm p-4 mb-4">
                <div className="flex items-start space-x-2 mb-3">
                  <AlertTriangle className="w-5 h-5 text-red-600 mt-0.5 flex-shrink-0" />
                  <div>
                    <p className="text-sm font-bold text-red-900 mb-1">
                      {t('profile:modal.delete.warningTitle')}
                    </p>
                    <p className="text-xs text-red-700">
                      The following will be permanently deleted:
                    </p>
                  </div>
                </div>
                <ul className="text-sm text-red-800 space-y-1.5 ml-7">
                  <li className="flex items-center">
                    <span className="w-1.5 h-1.5 bg-red-600 rounded-full mr-2"></span>
                    <Bot className="w-3.5 h-3.5 mr-1.5 flex-shrink-0" />
                    {stats?.total_agents} {t('profile:modal.delete.warningItems.agents')}
                  </li>
                  <li className="flex items-center">
                    <span className="w-1.5 h-1.5 bg-red-600 rounded-full mr-2"></span>
                    <FileText className="w-3.5 h-3.5 mr-1.5 flex-shrink-0" />
                    {stats?.total_documents} {t('profile:modal.delete.warningItems.documents')}
                  </li>
                  <li className="flex items-center">
                    <span className="w-1.5 h-1.5 bg-red-600 rounded-full mr-2"></span>
                    <MessageCircle className="w-3.5 h-3.5 mr-1.5 flex-shrink-0" />
                    {stats?.total_conversations} {t('profile:modal.delete.warningItems.conversations')}
                  </li>
                  <li className="flex items-center">
                    <span className="w-1.5 h-1.5 bg-red-600 rounded-full mr-2"></span>
                    <User className="w-3.5 h-3.5 mr-1.5 flex-shrink-0" />
                    {t('profile:modal.delete.warningItems.teams')}
                  </li>
                </ul>
              </div>
            </div>

            {/* Modal Footer */}
            <div className="px-6 py-4 bg-gray-50 rounded-b-card flex flex-col-reverse sm:flex-row gap-3">
              <button
                onClick={() => setShowDeleteConfirm(false)}
                className="flex-1 px-4 py-2.5 bg-white hover:bg-gray-100 text-gray-700 border border-gray-300 rounded-sm font-medium transition-colors disabled:opacity-50"
                disabled={deleteLoading}
              >
                {t('profile:modal.buttons.cancel')}
              </button>
              <button
                onClick={handleDeleteAccount}
                disabled={deleteLoading}
                className="flex-1 px-4 py-2.5 rounded-sm font-medium text-white transition-colors disabled:opacity-50 disabled:cursor-not-allowed bg-red-600 hover:bg-red-700"
              >
                {deleteLoading ? (
                  <div className="flex items-center justify-center space-x-2">
                    <Loader2 className="w-4 h-4 animate-spin" />
                    <span>{t('profile:modal.buttons.processing')}</span>
                  </div>
                ) : (
                  <span>Confirm Deletion</span>
                )}
              </button>
            </div>
          </div>
        </div>
      )}
    </Layout>
  );
}

export async function getServerSideProps({ locale }) {
  // Auth check is handled client-side via useAuth hook
  return {
    props: {
      ...(await serverSideTranslations(locale, ['profile', 'common', 'errors'])),
    },
  };
}
