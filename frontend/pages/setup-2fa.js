import { useState, useEffect, useRef } from "react";
import { useRouter } from "next/router";
import axios from "axios";
import toast, { Toaster } from "react-hot-toast";
import { Shield, KeyRound, Copy, CheckCircle, Loader2 } from "lucide-react";
import Image from "next/image";
import { useTranslation } from 'next-i18next';
import { serverSideTranslations } from 'next-i18next/serverSideTranslations';
import LanguageSwitcher from '../components/LanguageSwitcher';

const getApiUrl = () => {
  if (process.env.NEXT_PUBLIC_API_URL) {
    return process.env.NEXT_PUBLIC_API_URL;
  }
  if (typeof window !== "undefined" && window.location.hostname.includes("run.app")) {
    return window.location.origin.replace("frontend", "backend");
  }
  return "http://localhost:8080";
};

const API_URL = getApiUrl();

export default function Setup2FA() {
  const { t } = useTranslation(['auth', 'errors']);
  const router = useRouter();

  // Steps: 1 = QR code, 2 = confirm code
  const [step, setStep] = useState(1);
  const [loading, setLoading] = useState(true);
  const [qrCode, setQrCode] = useState("");
  const [secret, setSecret] = useState("");
  const [verifyCode, setVerifyCode] = useState("");
  const [verifying, setVerifying] = useState(false);
  const codeInputRef = useRef(null);

  useEffect(() => {
    const setupToken = sessionStorage.getItem("setup_token");
    if (!setupToken) {
      router.replace("/login");
      return;
    }
    initSetup(setupToken);
  }, []);

  useEffect(() => {
    if (step === 2 && codeInputRef.current) {
      codeInputRef.current.focus();
    }
  }, [step]);

  const initSetup = async (token) => {
    try {
      const response = await axios.post(`${API_URL}/auth/2fa/setup`, {}, {
        headers: { Authorization: `Bearer ${token}` }
      });
      setQrCode(response.data.qr_code);
      setSecret(response.data.secret);
    } catch (error) {
      if (error.response?.status === 401) {
        sessionStorage.removeItem("setup_token");
        toast.error(t('auth:twoFactor.sessionExpired'));
        router.replace("/login");
        return;
      }
      toast.error(t('auth:errors.generic'));
    } finally {
      setLoading(false);
    }
  };

  const handleConfirm = async (e) => {
    e.preventDefault();
    if (!verifyCode.trim()) return;
    setVerifying(true);

    try {
      const setupToken = sessionStorage.getItem("setup_token");
      if (!setupToken) {
        toast.error(t('auth:twoFactor.sessionExpired'));
        router.replace("/login");
        return;
      }

      const response = await axios.post(`${API_URL}/auth/2fa/confirm-setup`, {
        code: verifyCode.trim()
      }, {
        headers: { Authorization: `Bearer ${setupToken}` },
        withCredentials: true
      });

      // Clean up setup token - cookie is set by backend
      sessionStorage.removeItem("setup_token");

      toast.success(t('auth:twoFactor.setup.setupComplete'));
      window.location.href = "/agents";
    } catch (error) {
      const detail = error.response?.data?.detail || t('auth:twoFactor.invalidCode');
      toast.error(detail);
      setVerifyCode("");
    } finally {
      setVerifying(false);
    }
  };

  const handleCopySecret = () => {
    navigator.clipboard.writeText(secret);
    toast.success(t('auth:twoFactor.secretCopied'));
  };

  if (loading) {
    return (
      <div className="min-h-screen bg-gray-50 flex items-center justify-center">
        <div className="flex flex-col items-center space-y-4">
          <Loader2 className="w-12 h-12 text-primary-600 animate-spin" />
          <p className="text-xl font-semibold text-gray-700">{t('auth:twoFactor.settingUp')}</p>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen flex flex-col items-center justify-center bg-gray-50 relative overflow-hidden py-8">

      <div className="absolute top-6 right-6 z-20">
        <LanguageSwitcher />
      </div>

      <Toaster position="top-right" />

      {/* Logo */}
      <div className="relative z-10 mb-6 group">
        <div className="relative">
          <Image src="/logo-and.png" alt="Logo Taic" width={80} height={80} className="drop-shadow-2xl" />
        </div>
      </div>

      {/* Progress Steps */}
      <div className="relative z-10 flex items-center space-x-4 mb-8">
        {[1, 2].map((s) => (
          <div key={s} className="flex items-center">
            <div className={`w-10 h-10 rounded-full flex items-center justify-center font-bold text-sm transition-all duration-300 ${
              step >= s
                ? "bg-gradient-to-br from-blue-500 to-purple-500 text-white shadow-card"
                : "bg-gray-200 text-gray-500"
            }`}>
              {step > s ? <CheckCircle className="w-5 h-5" /> : s}
            </div>
            {s < 2 && (
              <div className={`w-12 h-1 mx-2 rounded transition-all duration-300 ${
                step > s ? "bg-gradient-to-r from-blue-500 to-purple-500" : "bg-gray-200"
              }`} />
            )}
          </div>
        ))}
      </div>

      <div className="relative z-10 sm:mx-auto sm:w-full sm:max-w-lg px-4">
        <div className="bg-white py-8 px-6 shadow-card rounded-card border border-gray-100 animate-fade-in sm:px-10">

          {/* Step 1: QR Code */}
          {step === 1 && (
            <div>
              <div className="text-center mb-6">
                <div className="w-16 h-16 mx-auto mb-4 rounded-card bg-gradient-to-br from-blue-500 to-purple-500 flex items-center justify-center shadow-card">
                  <Shield className="w-8 h-8 text-white" />
                </div>
                <h2 className="text-2xl font-bold text-gray-900 mb-2">{t('auth:twoFactor.setup.title')}</h2>
                <p className="text-gray-600">{t('auth:twoFactor.setup.scanQR')}</p>
              </div>

              {/* QR Code */}
              {qrCode && (
                <div className="flex justify-center mb-6">
                  <div className="p-4 bg-white rounded-card shadow-inner border border-gray-100">
                    <img src={qrCode} alt="QR Code" className="w-48 h-48" />
                  </div>
                </div>
              )}

              {/* Manual secret */}
              <div className="mb-6">
                <p className="text-sm text-gray-600 mb-2 text-center">{t('auth:twoFactor.setup.manualEntry')}</p>
                <div className="flex items-center space-x-2">
                  <code className="flex-1 px-4 py-3 bg-gray-100 rounded-sm text-sm font-mono text-center break-all select-all">
                    {secret}
                  </code>
                  <button
                    onClick={handleCopySecret}
                    className="p-3 bg-gray-100 hover:bg-gray-200 rounded-sm transition-colors"
                    title={t('auth:twoFactor.setup.copySecret')}
                  >
                    <Copy className="w-5 h-5 text-gray-600" />
                  </button>
                </div>
              </div>

              <button
                onClick={() => setStep(2)}
                className="w-full py-3 px-4 bg-gradient-to-r from-blue-600 to-purple-600 hover:from-blue-700 hover:to-purple-700 text-white font-bold rounded-button shadow-card hover:shadow-elevated transition-all duration-300"
              >
                {t('auth:twoFactor.setup.next')}
              </button>
            </div>
          )}

          {/* Step 2: Verify Code */}
          {step === 2 && (
            <div>
              <div className="text-center mb-6">
                <div className="w-16 h-16 mx-auto mb-4 rounded-card bg-gradient-to-br from-purple-500 to-pink-500 flex items-center justify-center shadow-card">
                  <KeyRound className="w-8 h-8 text-white" />
                </div>
                <h2 className="text-2xl font-bold text-gray-900 mb-2">{t('auth:twoFactor.setup.verifyTitle')}</h2>
                <p className="text-gray-600">{t('auth:twoFactor.setup.verifyDescription')}</p>
              </div>

              <form onSubmit={handleConfirm}>
                <input
                  ref={codeInputRef}
                  type="text"
                  value={verifyCode}
                  onChange={(e) => setVerifyCode(e.target.value)}
                  placeholder="000000"
                  className="w-full px-4 py-4 text-center text-3xl tracking-[0.5em] border border-gray-200 rounded-input bg-white focus:outline-none focus:ring-2 focus:ring-purple-500 focus:border-purple-500 transition-all font-mono mb-6"
                  maxLength={6}
                  inputMode="numeric"
                  autoComplete="one-time-code"
                />

                <div className="flex space-x-3">
                  <button
                    type="button"
                    onClick={() => setStep(1)}
                    className="flex-1 py-3 px-4 bg-white border border-gray-200 hover:bg-gray-50 text-gray-700 font-medium rounded-button transition-colors"
                  >
                    {t('auth:twoFactor.setup.back')}
                  </button>
                  <button
                    type="submit"
                    disabled={verifying || verifyCode.length < 6}
                    className="flex-1 py-3 px-4 bg-gradient-to-r from-purple-600 to-pink-600 hover:from-purple-700 hover:to-pink-700 text-white font-bold rounded-button shadow-card hover:shadow-elevated disabled:opacity-50 disabled:cursor-not-allowed transition-all duration-300"
                  >
                    {verifying ? (
                      <div className="flex items-center justify-center">
                        <Loader2 className="w-5 h-5 animate-spin mr-2" />
                        <span>{t('auth:twoFactor.verifying')}</span>
                      </div>
                    ) : (
                      <div className="flex items-center justify-center space-x-2">
                        <CheckCircle className="w-5 h-5" />
                        <span>{t('auth:twoFactor.setup.finish')}</span>
                      </div>
                    )}
                  </button>
                </div>
              </form>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

export async function getStaticProps({ locale }) {
  return {
    props: {
      ...(await serverSideTranslations(locale, ['auth', 'errors', 'common'])),
    },
  };
}
