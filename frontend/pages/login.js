import { useState, useRef, useEffect } from 'react';
import { useRouter } from 'next/router';
import axios from 'axios';
import toast, { Toaster } from 'react-hot-toast';
import { LogIn, UserPlus, Mail, Lock, User, Shield, KeyRound, Building2, CheckCircle, XCircle } from 'lucide-react';
import Image from 'next/image';
import { useTranslation } from 'next-i18next';
import { serverSideTranslations } from 'next-i18next/serverSideTranslations';
import LanguageSwitcher from '../components/LanguageSwitcher';
import { GoogleOAuthProvider, GoogleLogin } from '@react-oauth/google';

const getApiUrl = () => {
  if (process.env.NEXT_PUBLIC_API_URL) return process.env.NEXT_PUBLIC_API_URL;
  if (typeof window !== 'undefined' && window.location.hostname.includes('run.app'))
    return window.location.origin.replace('frontend', 'backend');
  return 'http://localhost:8080';
};
const API_URL = getApiUrl();

const PW_RULES = [
  { key: 'minLength', test: (p) => p.length >= 8 },
  { key: 'uppercase', test: (p) => /[A-Z]/.test(p) },
  { key: 'lowercase', test: (p) => /[a-z]/.test(p) },
  { key: 'digit',     test: (p) => /[0-9]/.test(p) },
];

function PasswordRules({ password, t }) {
  return (
    <div className="mt-3 space-y-1.5">
      {PW_RULES.map(({ key, test }) => {
        const ok = test(password);
        return (
          <div key={key} className={`flex items-center gap-2 text-xs transition-colors ${password.length === 0 ? 'text-gray-400' : ok ? 'text-green-600' : 'text-red-500'}`}>
            {ok ? <CheckCircle className="w-3.5 h-3.5" /> : <XCircle className="w-3.5 h-3.5" />}
            {t(`auth:passwordRules.${key}`)}
          </div>
        );
      })}
    </div>
  );
}

function AuthInput({ id, name, type = 'text', label, placeholder, Icon, value, onChange, children }) {
  return (
    <div>
      <label htmlFor={id} className="block text-sm font-semibold text-gray-700 mb-1.5">
        {label}
      </label>
      <div className="relative">
        {Icon && (
          <div className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400">
            <Icon className="w-4 h-4" />
          </div>
        )}
        <input
          id={id} name={name} type={type} required
          value={value} onChange={onChange}
          placeholder={placeholder}
          className="w-full px-4 py-3 pl-10 border border-gray-200 rounded-input bg-white text-sm placeholder-gray-400 focus:outline-none focus:ring-2 focus:ring-primary-500 focus:border-primary-500 transition-all"
        />
      </div>
      {children}
    </div>
  );
}

const FEATURES = [
  'Agents IA spécialisés par métier',
  'RAG sur vos documents internes',
  'Connexion Notion & Google Drive',
  'Équipes multi-agents partagées',
];

export default function Login() {
  const { t } = useTranslation(['auth', 'errors']);
  const [isLogin, setIsLogin] = useState(true);
  const [formData, setFormData] = useState({ username: '', email: '', password: '', invite_code: '' });
  const [loading, setLoading] = useState(false);
  const router = useRouter();

  const [show2FA, setShow2FA] = useState(false);
  const [totpCode, setTotpCode] = useState('');
  const [verifying2FA, setVerifying2FA] = useState(false);
  const totpRef = useRef(null);

  const [showEmailVerif, setShowEmailVerif] = useState(false);
  const [verificationEmail, setVerificationEmail] = useState('');
  const [resending, setResending] = useState(false);

  useEffect(() => {
    if (show2FA && totpRef.current) totpRef.current.focus();
  }, [show2FA]);

  const handleChange = (e) => setFormData(p => ({ ...p, [e.target.name]: e.target.value }));

  const handleSubmit = async (e) => {
    e.preventDefault();
    setLoading(true);

    if (!isLogin) {
      const pw = formData.password;
      const errors = PW_RULES.filter(r => !r.test(pw)).map(r => t(`auth:passwordRules.${r.key}`));
      if (errors.length) { toast.error(errors.join('\n'), { duration: 5000 }); setLoading(false); return; }
    }

    try {
      const endpoint = isLogin ? '/login' : '/register';
      const registerPayload = { username: formData.username, email: formData.email, password: formData.password };
      if (formData.invite_code.trim()) registerPayload.invite_code = formData.invite_code.trim();
      const payload = isLogin
        ? { username: formData.username, password: formData.password }
        : registerPayload;

      const { data } = await axios.post(`${API_URL}${endpoint}`, payload, { withCredentials: true });

      if (isLogin) {
        if (data.requires_email_verification) { setVerificationEmail(data.email); setShowEmailVerif(true); setLoading(false); return; }
        if (data.requires_2fa_setup) { sessionStorage.setItem('setup_token', data.setup_token); toast.success(t('auth:twoFactor.setupRequired')); window.location.href = '/setup-2fa'; return; }
        if (data.requires_2fa) { sessionStorage.setItem('pre_2fa_token', data.pre_2fa_token); setShow2FA(true); setLoading(false); return; }
        toast.success(t('auth:login.success'));
        window.location.href = '/agents';
      } else {
        toast.success(t('auth:signup.success'));
        setIsLogin(true);
        setLoading(false);
      }
    } catch (error) {
      let errorMessage = t('auth:errors.generic');
      if (error.response) {
        const detail = error.response?.data?.detail;
        if (Array.isArray(detail)) {
          errorMessage = detail.map(err => err.msg || JSON.stringify(err)).join(', ');
        } else if (typeof detail === 'string') {
          errorMessage = detail;
        } else if (detail && typeof detail === 'object') {
          errorMessage = detail.msg || JSON.stringify(detail);
        } else {
          errorMessage = `${t('errors:network.unknown')} ${error.response.status}: ${error.response.statusText}`;
        }
      } else if (error.request) {
        errorMessage = t('errors:network.unreachable');
      } else {
        errorMessage = error.message;
      }
      toast.error(errorMessage);
      setLoading(false);
    }
  };

  const handleVerify2FA = async (e) => {
    e.preventDefault();
    if (!totpCode.trim()) return;
    setVerifying2FA(true);
    try {
      const token = sessionStorage.getItem('pre_2fa_token');
      if (!token) { toast.error(t('auth:twoFactor.sessionExpired')); setShow2FA(false); return; }
      await axios.post(`${API_URL}/auth/2fa/verify`, { code: totpCode.trim() }, { headers: { Authorization: `Bearer ${token}` }, withCredentials: true });
      sessionStorage.removeItem('pre_2fa_token');
      toast.success(t('auth:login.success'));
      window.location.href = '/agents';
    } catch (err) {
      toast.error(err.response?.data?.detail || t('auth:twoFactor.invalidCode'));
      setTotpCode('');
    } finally { setVerifying2FA(false); }
  };

  const handleGoogleSuccess = async (cred) => {
    try {
      const payload = { credential: cred.credential };
      if (!isLogin && formData.invite_code.trim()) payload.invite_code = formData.invite_code.trim();
      await axios.post(`${API_URL}/auth/google`, payload, { withCredentials: true });
      toast.success(t('auth:login.success'));
      window.location.href = '/agents';
    } catch (err) { toast.error(err.response?.data?.detail || t('auth:google.error')); }
  };

  const googleClientId = process.env.NEXT_PUBLIC_GOOGLE_CLIENT_ID;

  const content = (
    <div className="min-h-screen flex bg-white">
      <Toaster position="top-right" />

      {/* Left: brand panel */}
      <div className="hidden lg:flex w-[42%] shrink-0 flex-col justify-between bg-navy p-12 relative overflow-hidden">
        <div className="absolute -top-32 -right-32 w-[420px] h-[420px] rounded-full bg-primary-600 opacity-10" />
        <div className="absolute -bottom-24 -left-16 w-72 h-72 rounded-full bg-primary-600 opacity-[.07]" />

        <div className="relative z-10 flex items-center gap-3">
          <Image src="/logo-and.png" alt="TAIC" width={36} height={36} className="object-contain brightness-[10]" />
          <span className="font-heading font-extrabold text-xl text-white tracking-tight">TAIC</span>
        </div>

        <div className="relative z-10">
          <h2 className="font-heading font-extrabold text-[38px] text-white leading-[1.15] tracking-tight mb-5">
            Vos agents IA,<br />à portée de main
          </h2>
          <p className="text-[15px] text-white/60 leading-relaxed mb-10">
            Créez, configurez et déployez des assistants intelligents pour toute votre organisation.
          </p>
          <ul className="flex flex-col gap-3.5">
            {FEATURES.map(f => (
              <li key={f} className="flex items-center gap-3">
                <div className="w-5 h-5 rounded-full bg-primary-600 flex items-center justify-center shrink-0">
                  <svg className="w-2.5 h-2.5 text-white" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round"><polyline points="20,6 9,17 4,12"/></svg>
                </div>
                <span className="text-sm text-white/75">{f}</span>
              </li>
            ))}
          </ul>
        </div>

        <div className="relative z-10 flex gap-5">
          {['taic.co', 'Contact', 'CGU'].map(l => (
            <span key={l} className="text-xs text-white/30 cursor-pointer hover:text-white/60 transition-colors">{l}</span>
          ))}
        </div>
      </div>

      {/* Right: form */}
      <div className="flex-1 flex flex-col items-center justify-center px-8 py-12 overflow-y-auto">
        <div className="lg:hidden mb-8">
          <Image src="/logo-and.png" alt="TAIC" width={48} height={48} className="object-contain mx-auto" />
        </div>

        <div className="absolute top-5 right-6">
          <LanguageSwitcher />
        </div>

        <div className="w-full max-w-[400px]">
          <div className="mb-9">
            <h1 className="font-heading font-extrabold text-[28px] text-slate-900 tracking-tight mb-2">
              {isLogin ? t('auth:login.title') : t('auth:signup.title')}
            </h1>
            <p className="text-sm text-gray-500">{t('auth:login.subtitle')}</p>
          </div>

          <form onSubmit={handleSubmit} className="space-y-4">
            <AuthInput id="username" name="username" label={t('auth:login.username.label')} placeholder={t('auth:login.username.placeholder')} Icon={User} value={formData.username} onChange={handleChange} />

            {!isLogin && (
              <AuthInput id="email" name="email" type="email" label={t('auth:login.email.label')} placeholder={t('auth:login.email.placeholder')} Icon={Mail} value={formData.email} onChange={handleChange} />
            )}

            {!isLogin && (
              <AuthInput id="invite_code" name="invite_code" label={t('auth:inviteCode.label')} placeholder={t('auth:inviteCode.placeholder')} Icon={Building2} value={formData.invite_code} onChange={handleChange}>
                <p className="mt-1.5 text-xs text-gray-500">{t('auth:inviteCode.hint')}</p>
              </AuthInput>
            )}

            <AuthInput id="password" name="password" type="password" label={t('auth:login.password.label')} placeholder={t('auth:login.password.placeholder')} Icon={Lock} value={formData.password} onChange={handleChange}>
              {!isLogin && <PasswordRules password={formData.password} t={t} />}
              {isLogin && (
                <div className="mt-2 text-right">
                  <a href="/forgot-password" className="text-sm text-primary-600 font-medium hover:underline">
                    {t('auth:login.forgotPassword')}
                  </a>
                </div>
              )}
            </AuthInput>

            <button type="submit" disabled={loading}
              className="w-full flex items-center justify-center gap-2 py-3 bg-primary-600 hover:bg-primary-700 text-white font-semibold rounded-button transition-all disabled:opacity-50 disabled:cursor-not-allowed mt-2">
              {loading
                ? <><span className="w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin" /> {t('auth:login.loading')}</>
                : isLogin
                  ? <><LogIn className="w-4 h-4" /> {t('auth:login.button')}</>
                  : <><UserPlus className="w-4 h-4" /> {t('auth:signup.button')}</>
              }
            </button>

            <div className="flex items-center gap-3 my-1">
              <div className="flex-1 h-px bg-gray-200" />
              <span className="text-xs text-gray-400">{t('auth:login.or')}</span>
              <div className="flex-1 h-px bg-gray-200" />
            </div>

            {googleClientId && (
              <div className="flex justify-center">
                <GoogleLogin onSuccess={handleGoogleSuccess} onError={() => toast.error(t('auth:google.error'))} text="continue_with" shape="rectangular" size="large" width="368" />
              </div>
            )}

            <div className="text-center pt-1">
              <button type="button" onClick={() => setIsLogin(p => !p)}
                className="text-sm text-primary-600 font-medium hover:underline transition-colors">
                {isLogin ? t('auth:login.switchToSignup') : t('auth:signup.switchToLogin')}
              </button>
            </div>
          </form>
        </div>
      </div>

      {/* 2FA overlay */}
      {show2FA && (
        <div className="fixed inset-0 bg-black/50 backdrop-blur-sm flex items-center justify-center p-4 z-50">
          <div className="bg-white rounded-card shadow-floating max-w-md w-full animate-fade-in">
            <div className="px-6 py-5 border-b border-gray-100 flex items-center gap-3">
              <div className="w-10 h-10 rounded-button bg-gradient-to-br from-primary-500 to-primary-700 flex items-center justify-center">
                <Shield className="w-5 h-5 text-white" />
              </div>
              <div>
                <h3 className="font-heading font-bold text-gray-900">{t('auth:twoFactor.verifyTitle')}</h3>
                <p className="text-sm text-gray-500">{t('auth:twoFactor.verifySubtitle')}</p>
              </div>
            </div>
            <form onSubmit={handleVerify2FA} className="px-6 py-6 space-y-4">
              <div>
                <label className="block text-sm font-semibold text-gray-700 mb-2 flex items-center gap-2">
                  <KeyRound className="w-4 h-4 text-primary-600" /> {t('auth:twoFactor.codeLabel')}
                </label>
                <input ref={totpRef} type="text" value={totpCode} onChange={e => setTotpCode(e.target.value)}
                  placeholder={t('auth:twoFactor.codePlaceholder')}
                  className="w-full px-4 py-3 text-center text-2xl tracking-widest font-mono border border-gray-200 rounded-input focus:outline-none focus:ring-2 focus:ring-primary-500"
                  maxLength={6} autoComplete="one-time-code" inputMode="numeric" />
              </div>
              <button type="submit" disabled={verifying2FA || !totpCode.trim()}
                className="w-full py-3 bg-primary-600 hover:bg-primary-700 text-white font-semibold rounded-button transition-all disabled:opacity-50">
                {verifying2FA ? t('auth:twoFactor.verifying') : t('auth:twoFactor.verifyButton')}
              </button>
            </form>
            <div className="px-6 py-4 bg-gray-50 rounded-b-card">
              <button type="button" onClick={() => { setShow2FA(false); setTotpCode(''); sessionStorage.removeItem('pre_2fa_token'); }}
                className="w-full py-2 text-sm text-gray-500 hover:text-gray-800 transition-colors">
                {t('auth:twoFactor.cancel')}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Email verification overlay */}
      {showEmailVerif && (
        <div className="fixed inset-0 bg-black/50 backdrop-blur-sm flex items-center justify-center p-4 z-50">
          <div className="bg-white rounded-card shadow-floating max-w-md w-full animate-fade-in">
            <div className="px-6 py-5 border-b border-gray-100 flex items-center gap-3">
              <div className="w-10 h-10 rounded-button bg-gradient-to-br from-purple-500 to-pink-500 flex items-center justify-center">
                <Mail className="w-5 h-5 text-white" />
              </div>
              <h3 className="font-heading font-bold text-gray-900">{t('auth:emailVerification.required')}</h3>
            </div>
            <div className="px-6 py-6 space-y-4">
              <p className="text-sm text-gray-600">{t('auth:emailVerification.checkInbox', { email: verificationEmail })}</p>
              <button onClick={async () => {
                setResending(true);
                try {
                  await axios.post(`${API_URL}/auth/resend-verification`, { email: formData.email || formData.username });
                  toast.success(t('auth:emailVerification.resent'));
                } catch (e) {
                  toast.error(e.response?.data?.detail || t('auth:emailVerification.error'));
                } finally { setResending(false); }
              }}
                disabled={resending}
                className="w-full py-3 bg-primary-600 hover:bg-primary-700 text-white font-semibold rounded-button transition-all disabled:opacity-50">
                {resending ? t('auth:emailVerification.resending') : t('auth:emailVerification.resend')}
              </button>
            </div>
            <div className="px-6 py-4 bg-gray-50 rounded-b-card">
              <button type="button" onClick={() => setShowEmailVerif(false)} className="w-full py-2 text-sm text-gray-500 hover:text-gray-800 transition-colors">
                {t('auth:twoFactor.cancel')}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );

  return googleClientId ? <GoogleOAuthProvider clientId={googleClientId}>{content}</GoogleOAuthProvider> : content;
}

export async function getStaticProps({ locale }) {
  return { props: { ...(await serverSideTranslations(locale, ['auth', 'errors', 'common'])) } };
}
