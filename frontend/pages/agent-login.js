import { useState } from "react";
import { useRouter } from "next/router";
import axios from "axios";
import toast, { Toaster } from "react-hot-toast";
import { LogIn, Mail, Lock, Bot } from "lucide-react";
import { useTranslation } from 'next-i18next';
import { serverSideTranslations } from 'next-i18next/serverSideTranslations';

const getApiUrl = () => {
  if (process.env.NEXT_PUBLIC_API_URL) return process.env.NEXT_PUBLIC_API_URL;
  if (typeof window !== "undefined" && window.location.hostname.includes("run.app")) {
    return window.location.origin.replace("frontend", "backend");
  }
  return "http://localhost:8080";
};
const API_URL = getApiUrl();

export default function AgentLogin() {
  const { t } = useTranslation(['auth', 'errors']);
  const [formData, setFormData] = useState({ email: "", password: "" });
  const [loading, setLoading] = useState(false);
  const router = useRouter();

  const handleSubmit = async (e) => {
    e.preventDefault();
    setLoading(true);
    try {
      const response = await axios.post(`${API_URL}/login-agent`, formData, {
        withCredentials: true
      });

      toast.success(t('auth:agentLogin.success'));
      router.push(`/chat/${response.data.agent_id}`);
    } catch (err) {
      toast.error(t('auth:agentLogin.error'));
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen flex items-center justify-center bg-gray-50 p-4">

      <Toaster position="top-right" />

      <div className="bg-white p-8 rounded-card shadow-card w-full max-w-md border border-gray-100 animate-fade-in">
        <div className="text-center mb-8">
          <div className="inline-flex items-center justify-center w-16 h-16 rounded-full bg-gradient-to-br from-blue-100 to-purple-100 mb-4 relative">
            <Bot className="w-8 h-8 text-blue-600" />
            <div className="absolute -top-1 -right-1 w-4 h-4 bg-green-500 rounded-full border-2 border-white animate-pulse"></div>
          </div>
          <h1 className="text-3xl font-heading font-bold text-gray-900 mb-2 flex items-center justify-center gap-2">
            {t('auth:agentLogin.title')}
          </h1>
          <p className="text-gray-600">{t('auth:agentLogin.subtitle')}</p>
        </div>

        <form onSubmit={handleSubmit} className="space-y-5">
          <div>
            <label className="block text-sm font-semibold text-gray-700 mb-2 flex items-center">
              <Mail className="w-4 h-4 mr-2 text-blue-600" />
              {t('auth:agentLogin.email.label')}
            </label>
            <div className="relative">
              <input
                type="email"
                className="appearance-none block w-full px-4 py-3 pl-11 border border-gray-200 rounded-input placeholder-gray-400 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-blue-500 transition-all duration-300 bg-white"
                placeholder={t('auth:agentLogin.email.placeholder')}
                value={formData.email}
                onChange={e => setFormData(f => ({ ...f, email: e.target.value }))}
                required
              />
              <div className="absolute left-3 top-1/2 -translate-y-1/2">
                <Mail className="w-5 h-5 text-gray-400" />
              </div>
            </div>
          </div>

          <div>
            <label className="block text-sm font-semibold text-gray-700 mb-2 flex items-center">
              <Lock className="w-4 h-4 mr-2 text-purple-600" />
              {t('auth:agentLogin.password.label')}
            </label>
            <div className="relative">
              <input
                type="password"
                className="appearance-none block w-full px-4 py-3 pl-11 border border-gray-200 rounded-input placeholder-gray-400 focus:outline-none focus:ring-2 focus:ring-purple-500 focus:border-purple-500 transition-all duration-300 bg-white"
                placeholder={t('auth:agentLogin.password.placeholder')}
                value={formData.password}
                onChange={e => setFormData(f => ({ ...f, password: e.target.value }))}
                required
              />
              <div className="absolute left-3 top-1/2 -translate-y-1/2">
                <Lock className="w-5 h-5 text-gray-400" />
              </div>
            </div>
          </div>

          <button
            type="submit"
            className="group w-full flex justify-center items-center py-4 px-6 border-none rounded-button shadow-card hover:shadow-elevated text-base font-bold text-white bg-gradient-to-r from-blue-600 to-purple-600 hover:from-blue-700 hover:to-purple-700 focus:outline-none focus:ring-4 focus:ring-blue-300 disabled:opacity-50 disabled:cursor-not-allowed transition-all"
            disabled={loading}
          >
            {loading ? (
              <div className="flex items-center">
                <div className="animate-spin rounded-full h-6 w-6 border-b-2 border-white mr-3"></div>
                <span>{t('auth:agentLogin.connecting')}</span>
              </div>
            ) : (
              <div className="flex items-center">
                <LogIn className="w-6 h-6 mr-3 group-hover:scale-110 transition-transform" />
                <span>{t('auth:agentLogin.button')}</span>
              </div>
            )}
          </button>
        </form>

        <div className="mt-6">
          <div className="relative">
            <div className="absolute inset-0 flex items-center">
              <div className="w-full border-t border-gray-200"></div>
            </div>
            <div className="relative flex justify-center text-sm">
              <span className="px-4 bg-white text-gray-500 font-medium">{t('auth:agentLogin.infoTitle')}</span>
            </div>
          </div>

          <div className="mt-4 p-4 bg-gradient-to-br from-blue-50 to-purple-50 rounded-button border border-blue-200">
            <p className="text-xs text-center text-gray-600">
              <span className="font-semibold text-blue-700">{t('auth:agentLogin.infoReserved')}</span> {t('auth:agentLogin.infoMessage')} <a href="/login" className="text-blue-600 hover:underline font-semibold">{t('auth:agentLogin.normalLoginLink')}</a>.
            </p>
          </div>
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
