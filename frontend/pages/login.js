import { useState, useRef, useEffect } from "react";
import { useRouter } from "next/router";
import axios from "axios";
import toast, { Toaster } from "react-hot-toast";
import { LogIn, UserPlus, Mail, Lock, User, Shield, KeyRound, Building2 } from "lucide-react";
import Image from "next/image";
import { useTranslation } from 'next-i18next';
import { serverSideTranslations } from 'next-i18next/serverSideTranslations';
import LanguageSwitcher from '../components/LanguageSwitcher';
import { GoogleOAuthProvider, GoogleLogin } from '@react-oauth/google';

// Auto-detect API URL based on environment
const getApiUrl = () => {
  if (process.env.NEXT_PUBLIC_API_URL) {
    return process.env.NEXT_PUBLIC_API_URL;
  }

  // If in production (Cloud Run), try to detect backend URL
  if (typeof window !== "undefined" && window.location.hostname.includes("run.app")) {
    return window.location.origin.replace("frontend", "backend");
  }

  // Fallback to localhost
  return "http://localhost:8080";
};

const API_URL = getApiUrl();

export default function Login() {
  const { t } = useTranslation(['auth', 'errors']);
  const [isLogin, setIsLogin] = useState(true);
  const [formData, setFormData] = useState({
    username: "",
    email: "",
    password: "",
    invite_code: "",
  });
  const [loading, setLoading] = useState(false);
  const router = useRouter();

  // 2FA state
  const [show2FAOverlay, setShow2FAOverlay] = useState(false);
  const [totpCode, setTotpCode] = useState("");
  const [verifying2FA, setVerifying2FA] = useState(false);
  const totpInputRef = useRef(null);

  // Email verification state
  const [showEmailVerification, setShowEmailVerification] = useState(false);
  const [verificationEmail, setVerificationEmail] = useState("");
  const [resendingEmail, setResendingEmail] = useState(false);

  useEffect(() => {
    if (show2FAOverlay && totpInputRef.current) {
      totpInputRef.current.focus();
    }
  }, [show2FAOverlay]);

  const handleSubmit = async (e) => {
    e.preventDefault();
    setLoading(true);

    // Client-side password validation for registration
    if (!isLogin) {
      const pw = formData.password;
      const errors = [];
      if (pw.length < 8) errors.push(t('auth:passwordRules.minLength'));
      if (!/[A-Z]/.test(pw)) errors.push(t('auth:passwordRules.uppercase'));
      if (!/[a-z]/.test(pw)) errors.push(t('auth:passwordRules.lowercase'));
      if (!/[0-9]/.test(pw)) errors.push(t('auth:passwordRules.digit'));
      if (errors.length > 0) {
        toast.error(errors.join('\n'), { duration: 5000 });
        setLoading(false);
        return;
      }
    }

    try {
      const endpoint = isLogin ? "/login" : "/register";
      const registerPayload = { username: formData.username, email: formData.email, password: formData.password };
      if (formData.invite_code.trim()) registerPayload.invite_code = formData.invite_code.trim();
      const payload = isLogin
        ? { username: formData.username, password: formData.password }
        : registerPayload;

      const response = await axios.post(`${API_URL}${endpoint}`, payload, {
        withCredentials: true
      });

      if (isLogin) {
        const data = response.data;

        // Case 0: Email not verified
        if (data.requires_email_verification) {
          setVerificationEmail(data.email);
          setShowEmailVerification(true);
          setLoading(false);
          return;
        }

        // Case 1: User needs to set up 2FA
        if (data.requires_2fa_setup) {
          sessionStorage.setItem("setup_token", data.setup_token);
          toast.success(t('auth:twoFactor.setupRequired'));
          window.location.href = "/setup-2fa";
          return;
        }

        // Case 2: User has 2FA enabled, needs verification
        if (data.requires_2fa) {
          sessionStorage.setItem("pre_2fa_token", data.pre_2fa_token);
          setShow2FAOverlay(true);
          setLoading(false);
          return;
        }

        // Case 3: Normal login (2FA already completed / full token)
        localStorage.setItem("token", data.access_token);
        toast.success(t('auth:login.success'));
        window.location.href = "/agents";
        return;
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
      const pre2faToken = sessionStorage.getItem("pre_2fa_token");
      if (!pre2faToken) {
        toast.error(t('auth:twoFactor.sessionExpired'));
        setShow2FAOverlay(false);
        return;
      }

      const response = await axios.post(`${API_URL}/auth/2fa/verify`, {
        code: totpCode.trim()
      }, {
        headers: { Authorization: `Bearer ${pre2faToken}` },
        withCredentials: true
      });

      // Clean up and store full token
      sessionStorage.removeItem("pre_2fa_token");
      localStorage.setItem("token", response.data.access_token);

      toast.success(t('auth:login.success'));
      window.location.href = "/agents";
    } catch (error) {
      const detail = error.response?.data?.detail || t('auth:twoFactor.invalidCode');
      toast.error(detail);
      setTotpCode("");
    } finally {
      setVerifying2FA(false);
    }
  };

  const handleChange = (e) => {
    setFormData({
      ...formData,
      [e.target.name]: e.target.value,
    });
  };

  const handleResendVerification = async () => {
    setResendingEmail(true);
    try {
      // Use the actual email from form (for resend, we need the real email)
      const email = formData.email || formData.username;
      await axios.post(`${API_URL}/auth/resend-verification`, { email });
      toast.success(t('auth:emailVerification.resent'));
    } catch (err) {
      toast.error(err.response?.data?.detail || t('auth:emailVerification.error'));
    } finally {
      setResendingEmail(false);
    }
  };

  const handleGoogleSuccess = async (credentialResponse) => {
    try {
      const payload = { credential: credentialResponse.credential };
      if (!isLogin && formData.invite_code.trim()) {
        payload.invite_code = formData.invite_code.trim();
      }
      const response = await axios.post(`${API_URL}/auth/google`, payload, {
        withCredentials: true
      });
      localStorage.setItem("token", response.data.access_token);
      toast.success(t('auth:login.success'));
      window.location.href = "/agents";
    } catch (err) {
      toast.error(err.response?.data?.detail || t('auth:google.error'));
    }
  };

  const googleClientId = process.env.NEXT_PUBLIC_GOOGLE_CLIENT_ID;

  const content = (
    <div className="min-h-screen flex flex-col items-center justify-center bg-gray-50 relative overflow-hidden">
      {/* Subtle background gradient */}
      <div className="absolute inset-0 pointer-events-none">
        <div className="absolute inset-0 bg-gradient-to-br from-blue-50/80 via-white to-purple-50/60" />
      </div>

      {/* Language Switcher - Top Right */}
      <div className="absolute top-6 right-6 z-20">
        <LanguageSwitcher />
      </div>

      <Toaster position="top-right" />

      {/* Logo */}
      <div className="relative z-10 mb-8">
        <a href="https://taic.co" target="_blank" rel="noopener noreferrer">
          <Image
            src="/logo-and.png"
            alt="Logo Taic"
            width={90}
            height={90}
            className="cursor-pointer transition-opacity duration-300 hover:opacity-80"
          />
        </a>
      </div>

      <div className="relative z-10 sm:mx-auto sm:w-full sm:max-w-md px-4">
        <div className="text-center mb-8">
          <h2 className="font-heading text-3xl font-bold text-gray-900 mb-2">
            {isLogin ? t('auth:login.title') : t('auth:signup.title')}
          </h2>
          <p className="text-base text-gray-500">
            {t('auth:login.subtitle')}
          </p>
        </div>

        <div className="bg-white py-10 px-6 shadow-card rounded-card border border-gray-100 animate-fade-in sm:px-12">
          <form className="space-y-5" onSubmit={handleSubmit}>
            <div>
              <label htmlFor="username" className="block text-sm font-medium text-gray-700 mb-1.5 flex items-center">
                <User className="w-4 h-4 mr-2 text-blue-600" />
                {t('auth:login.username.label')}
              </label>
              <div className="relative">
                <input
                  id="username"
                  name="username"
                  type="text"
                  required
                  value={formData.username}
                  onChange={handleChange}
                  className="appearance-none block w-full px-4 py-3 pl-11 border border-gray-200 rounded-input placeholder-gray-400 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-blue-500 transition-all bg-white"
                  placeholder={t('auth:login.username.placeholder')}
                />
                <div className="absolute left-3 top-1/2 -translate-y-1/2">
                  <User className="w-5 h-5 text-gray-400" />
                </div>
              </div>
            </div>

            {!isLogin && (
              <div className="animate-fade-in">
                <label htmlFor="email" className="block text-sm font-medium text-gray-700 mb-1.5 flex items-center">
                  <Mail className="w-4 h-4 mr-2 text-purple-600" />
                  {t('auth:login.email.label')}
                </label>
                <div className="relative">
                  <input
                    id="email"
                    name="email"
                    type="email"
                    required
                    value={formData.email}
                    onChange={handleChange}
                    className="appearance-none block w-full px-4 py-3 pl-11 border border-gray-200 rounded-input placeholder-gray-400 focus:outline-none focus:ring-2 focus:ring-purple-500 focus:border-purple-500 transition-all bg-white"
                    placeholder={t('auth:login.email.placeholder')}
                  />
                  <div className="absolute left-3 top-1/2 -translate-y-1/2">
                    <Mail className="w-5 h-5 text-gray-400" />
                  </div>
                </div>
              </div>
            )}

            {!isLogin && (
              <div className="animate-fade-in">
                <label htmlFor="invite_code" className="block text-sm font-medium text-gray-700 mb-1.5 flex items-center">
                  <Building2 className="w-4 h-4 mr-2 text-teal-600" />
                  {t('auth:inviteCode.label')}
                </label>
                <div className="relative">
                  <input
                    id="invite_code"
                    name="invite_code"
                    type="text"
                    value={formData.invite_code}
                    onChange={handleChange}
                    className="appearance-none block w-full px-4 py-3 pl-11 border border-gray-200 rounded-input placeholder-gray-400 focus:outline-none focus:ring-2 focus:ring-teal-500 focus:border-teal-500 transition-all bg-white"
                    placeholder={t('auth:inviteCode.placeholder')}
                  />
                  <div className="absolute left-3 top-1/2 -translate-y-1/2">
                    <Building2 className="w-5 h-5 text-gray-400" />
                  </div>
                </div>
                <p className="mt-1 text-xs text-gray-500">{t('auth:inviteCode.hint')}</p>
              </div>
            )}

            <div>
              <label htmlFor="password" className="block text-sm font-medium text-gray-700 mb-1.5 flex items-center">
                <Lock className="w-4 h-4 mr-2 text-pink-600" />
                {t('auth:login.password.label')}
              </label>
              <div className="relative">
                <input
                  id="password"
                  name="password"
                  type="password"
                  required
                  value={formData.password}
                  onChange={handleChange}
                  className="appearance-none block w-full px-4 py-3 pl-11 border border-gray-200 rounded-input placeholder-gray-400 focus:outline-none focus:ring-2 focus:ring-pink-500 focus:border-pink-500 transition-all bg-white"
                  placeholder={t('auth:login.password.placeholder')}
                />
                <div className="absolute left-3 top-1/2 -translate-y-1/2">
                  <Lock className="w-5 h-5 text-gray-400" />
                </div>
              </div>
              {/* Password rules visible only in signup mode */}
              {!isLogin && (
                <div className="mt-3 space-y-1">
                  {[
                    { key: 'minLength', test: formData.password.length >= 8 },
                    { key: 'uppercase', test: /[A-Z]/.test(formData.password) },
                    { key: 'lowercase', test: /[a-z]/.test(formData.password) },
                    { key: 'digit', test: /[0-9]/.test(formData.password) },
                  ].map(({ key, test }) => (
                    <div key={key} className={`flex items-center text-xs transition-colors ${
                      formData.password.length === 0 ? 'text-gray-400' : test ? 'text-green-600' : 'text-red-500'
                    }`}>
                      <span className="mr-1.5">{formData.password.length === 0 ? '○' : test ? '✓' : '✗'}</span>
                      {t(`auth:passwordRules.${key}`)}
                    </div>
                  ))}
                </div>
              )}
              {/* Forgot password link */}
              {isLogin && (
                <div className="mt-3 text-right">
                  <a href="/forgot-password" className="text-blue-600 hover:text-blue-700 text-sm font-medium hover:underline transition-colors">
                    {t('auth:login.forgotPassword')}
                  </a>
                </div>
              )}
            </div>
            <div className="pt-2">
              <button
                type="submit"
                disabled={loading}
                className="w-full flex justify-center items-center py-3.5 px-6 border-none rounded-button text-base font-semibold text-white bg-gradient-to-r from-blue-600 to-purple-600 hover:from-blue-700 hover:to-purple-700 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-2 disabled:opacity-50 disabled:cursor-not-allowed transition-all hover:shadow-elevated"
              >
                {loading ? (
                  <div className="flex items-center">
                    <div className="animate-spin rounded-full h-5 w-5 border-b-2 border-white mr-3"></div>
                    <span>{t('auth:login.loading')}</span>
                  </div>
                ) : (
                  <div className="flex items-center">
                    {isLogin ? (
                      <>
                        <LogIn className="w-5 h-5 mr-2" />
                        <span>{t('auth:login.button')}</span>
                      </>
                    ) : (
                      <>
                        <UserPlus className="w-5 h-5 mr-2" />
                        <span>{t('auth:signup.button')}</span>
                      </>
                    )}
                  </div>
                )}
              </button>
            </div>

            <div className="relative">
              <div className="absolute inset-0 flex items-center">
                <div className="w-full border-t border-gray-200"></div>
              </div>
              <div className="relative flex justify-center text-sm">
                <span className="px-4 bg-white text-gray-500">{t('auth:login.or')}</span>
              </div>
            </div>

            {/* Google OAuth Button */}
            {googleClientId && (
              <div className="flex justify-center">
                <GoogleLogin
                  onSuccess={handleGoogleSuccess}
                  onError={() => toast.error(t('auth:google.error'))}
                  text="continue_with"
                  shape="pill"
                  size="large"
                  width="300"
                />
              </div>
            )}

            <div className="text-center">
              <button
                type="button"
                onClick={() => setIsLogin(!isLogin)}
                className="inline-flex items-center text-blue-600 hover:text-purple-600 text-sm font-medium transition-colors"
              >
                {isLogin ? (
                  <>
                    <UserPlus className="w-4 h-4 mr-2" />
                    {t('auth:login.switchToSignup')}
                  </>
                ) : (
                  <>
                    <LogIn className="w-4 h-4 mr-2" />
                    {t('auth:signup.switchToLogin')}
                  </>
                )}
              </button>
            </div>
          </form>
        </div>
      </div>

      {/* Email Verification Overlay */}
      {showEmailVerification && (
        <div className="fixed inset-0 bg-black/50 backdrop-blur-sm flex items-center justify-center p-4 z-50 animate-fade-in">
          <div className="bg-white rounded-card shadow-floating max-w-md w-full animate-scale-in">
            <div className="px-6 py-5 border-b border-gray-100 rounded-t-card">
              <div className="flex items-center space-x-3">
                <div className="w-10 h-10 rounded-button flex items-center justify-center bg-gradient-to-br from-purple-500 to-pink-500">
                  <Mail className="w-5 h-5 text-white" />
                </div>
                <div>
                  <h3 className="text-lg font-heading font-bold text-gray-900">{t('auth:emailVerification.required')}</h3>
                </div>
              </div>
            </div>

            <div className="px-6 py-6 space-y-4">
              <p className="text-gray-600 text-sm">
                {t('auth:emailVerification.checkInbox', { email: verificationEmail })}
              </p>

              <button
                onClick={handleResendVerification}
                disabled={resendingEmail}
                className="w-full py-3 px-4 bg-gradient-to-r from-purple-600 to-pink-600 hover:from-purple-700 hover:to-pink-700 text-white font-semibold rounded-button shadow-card disabled:opacity-50 disabled:cursor-not-allowed transition-all"
              >
                {resendingEmail ? t('auth:emailVerification.resending') : t('auth:emailVerification.resend')}
              </button>
            </div>

            <div className="px-6 py-4 bg-gray-50 rounded-b-card">
              <button
                type="button"
                onClick={() => setShowEmailVerification(false)}
                className="w-full py-2 text-gray-600 hover:text-gray-800 text-sm font-medium transition-colors"
              >
                {t('auth:twoFactor.cancel')}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* 2FA Verification Overlay */}
      {show2FAOverlay && (
        <div className="fixed inset-0 bg-black/50 backdrop-blur-sm flex items-center justify-center p-4 z-50 animate-fade-in">
          <div className="bg-white rounded-card shadow-floating max-w-md w-full animate-scale-in">
            <div className="px-6 py-5 border-b border-gray-100 rounded-t-card">
              <div className="flex items-center space-x-3">
                <div className="w-10 h-10 rounded-button flex items-center justify-center bg-gradient-to-br from-blue-500 to-purple-500">
                  <Shield className="w-5 h-5 text-white" />
                </div>
                <div>
                  <h3 className="text-lg font-heading font-bold text-gray-900">{t('auth:twoFactor.verifyTitle')}</h3>
                  <p className="text-sm text-gray-500">{t('auth:twoFactor.verifySubtitle')}</p>
                </div>
              </div>
            </div>

            <form onSubmit={handleVerify2FA} className="px-6 py-6">
              <div className="mb-4">
                <label className="block text-sm font-medium text-gray-700 mb-2 flex items-center">
                  <KeyRound className="w-4 h-4 mr-2 text-blue-600" />
                  {t('auth:twoFactor.codeLabel')}
                </label>
                <input
                  ref={totpInputRef}
                  type="text"
                  value={totpCode}
                  onChange={(e) => setTotpCode(e.target.value)}
                  placeholder={t('auth:twoFactor.codePlaceholder')}
                  className="w-full px-4 py-3 text-center text-2xl tracking-widest border border-gray-200 rounded-input focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-blue-500 transition-all bg-white font-mono"
                  maxLength={6}
                  autoComplete="one-time-code"
                  inputMode="numeric"
                />
              </div>

              <button
                type="submit"
                disabled={verifying2FA || !totpCode.trim()}
                className="w-full py-3 px-4 bg-gradient-to-r from-blue-600 to-purple-600 hover:from-blue-700 hover:to-purple-700 text-white font-semibold rounded-button shadow-card disabled:opacity-50 disabled:cursor-not-allowed transition-all"
              >
                {verifying2FA ? (
                  <div className="flex items-center justify-center">
                    <div className="animate-spin rounded-full h-5 w-5 border-b-2 border-white mr-2"></div>
                    <span>{t('auth:twoFactor.verifying')}</span>
                  </div>
                ) : (
                  t('auth:twoFactor.verifyButton')
                )}
              </button>
            </form>

            <div className="px-6 py-4 bg-gray-50 rounded-b-card">
              <button
                type="button"
                onClick={() => {
                  setShow2FAOverlay(false);
                  setTotpCode("");
                  sessionStorage.removeItem("pre_2fa_token");
                }}
                className="w-full py-2 text-gray-600 hover:text-gray-800 text-sm font-medium transition-colors"
              >
                {t('auth:twoFactor.cancel')}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );

  if (googleClientId) {
    return (
      <GoogleOAuthProvider clientId={googleClientId}>
        {content}
      </GoogleOAuthProvider>
    );
  }

  return content;
}

export async function getStaticProps({ locale }) {
  return {
    props: {
      ...(await serverSideTranslations(locale, ['auth', 'errors', 'common'])),
    },
  };
}
