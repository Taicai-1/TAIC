import { useState } from "react";
import axios from "axios";
import toast, { Toaster } from "react-hot-toast";
import { useRouter } from "next/router";
import { Lock, Sparkles, CheckCircle2, ArrowLeft } from "lucide-react";
import { useTranslation } from 'next-i18next';
import { serverSideTranslations } from 'next-i18next/serverSideTranslations';

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

export default function ResetPassword() {
  const { t } = useTranslation(['auth', 'errors']);
  const [newPassword, setNewPassword] = useState("");
  const [loading, setLoading] = useState(false);
  const [success, setSuccess] = useState(false);
  const router = useRouter();
  const { token } = router.query;

  const handleSubmit = async (e) => {
    e.preventDefault();
    setLoading(true);
    try {
      const res = await axios.post(`${API_URL}/reset-password`, {
        token,
        new_password: newPassword,
      });
      toast.success(t('auth:resetPassword.success'));
      setSuccess(true);
      setTimeout(() => router.push("/login"), 2000);
    } catch (err) {
      toast.error(err.response?.data?.detail || t('auth:resetPassword.error'));
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen flex flex-col justify-center items-center bg-gray-50 relative overflow-hidden p-4">

      <Toaster position="top-right" />

      <div className="relative z-10 bg-white p-8 rounded-card shadow-card w-full max-w-md border border-gray-100 animate-fade-in">
        <div className="text-center mb-8">
          <div className="inline-flex items-center justify-center w-16 h-16 rounded-full bg-gradient-to-br from-purple-100 to-pink-100 mb-4">
            <Lock className="w-8 h-8 text-purple-600" />
          </div>
          <h2 className="text-3xl font-heading font-bold bg-gradient-to-r from-blue-600 via-purple-600 to-pink-600 bg-clip-text text-transparent mb-2">
            {t('auth:resetPassword.title')}
          </h2>
          <p className="text-gray-600">{t('auth:resetPassword.subtitle')}</p>
        </div>

        {success ? (
          <div className="space-y-6">
            <div className="p-6 bg-gradient-to-br from-green-50 to-blue-50 border border-green-300 rounded-card">
              <div className="flex items-center mb-3">
                <CheckCircle2 className="w-6 h-6 text-green-600 mr-3 animate-pulse" />
                <h3 className="text-lg font-semibold text-green-800">{t('auth:resetPassword.success')}</h3>
              </div>
              <p className="text-green-700 text-sm">
                {t('auth:resetPassword.successMessage')}
              </p>
            </div>
            <div className="flex items-center justify-center space-x-2">
              <div className="animate-spin rounded-full h-5 w-5 border-b-2 border-primary-600"></div>
              <span className="text-gray-600 font-medium">{t('auth:resetPassword.redirecting')}</span>
            </div>
          </div>
        ) : (
          <form onSubmit={handleSubmit} className="space-y-6">
            <div>
              <label className="block text-sm font-semibold text-gray-700 mb-2 flex items-center">
                <Lock className="w-4 h-4 mr-2 text-purple-600" />
                {t('auth:resetPassword.newPassword.label')}
              </label>
              <div className="relative">
                <input
                  type="password"
                  placeholder={t('auth:resetPassword.newPassword.placeholder')}
                  value={newPassword}
                  onChange={e => setNewPassword(e.target.value)}
                  required
                  minLength={6}
                  className="appearance-none block w-full px-4 py-3 pl-11 border border-gray-200 rounded-input bg-white placeholder-gray-400 focus:outline-none focus:ring-2 focus:ring-purple-500 focus:border-purple-500 transition-all duration-300"
                />
                <div className="absolute left-3 top-1/2 -translate-y-1/2">
                  <Lock className="w-5 h-5 text-gray-400" />
                </div>
              </div>
              <p className="mt-2 text-xs text-gray-500">
                {t('auth:resetPassword.minChars')}
              </p>
            </div>

            <button
              type="submit"
              disabled={loading}
              className="group w-full flex justify-center items-center py-4 px-6 border-none rounded-button shadow-card hover:shadow-elevated text-base font-bold text-white bg-gradient-to-r from-blue-600 via-purple-600 to-pink-600 hover:from-blue-700 hover:via-purple-700 hover:to-pink-700 focus:outline-none focus:ring-4 focus:ring-purple-300 disabled:opacity-50 disabled:cursor-not-allowed transition-all duration-300"
            >
              {loading ? (
                <div className="flex items-center">
                  <div className="animate-spin rounded-full h-6 w-6 border-b-2 border-white mr-3"></div>
                  <span>{t('auth:resetPassword.resetting')}</span>
                </div>
              ) : (
                <div className="flex items-center">
                  <Lock className="w-6 h-6 mr-3 group-hover:scale-110 transition-transform" />
                  <span>{t('auth:resetPassword.button')}</span>
                  <Sparkles className="w-5 h-5 ml-3 group-hover:rotate-12 transition-transform" />
                </div>
              )}
            </button>
          </form>
        )}

        {!success && (
          <div className="mt-6 text-center">
            <button
              onClick={() => router.push('/login')}
              className="group inline-flex items-center text-primary-600 hover:text-purple-600 text-sm font-semibold transition-colors duration-300"
            >
              <ArrowLeft className="w-4 h-4 mr-2 group-hover:-translate-x-1 transition-transform" />
              {t('auth:resetPassword.backToLogin')}
            </button>
          </div>
        )}
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
