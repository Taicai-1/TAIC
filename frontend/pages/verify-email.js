import { useState, useEffect } from "react";
import axios from "axios";
import { useRouter } from "next/router";
import { CheckCircle2, XCircle, ArrowRight, Loader2 } from "lucide-react";
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

export default function VerifyEmail() {
  const { t } = useTranslation(['auth']);
  const router = useRouter();
  const { token } = router.query;
  const [status, setStatus] = useState("loading"); // loading | success | error
  const [errorMsg, setErrorMsg] = useState("");

  useEffect(() => {
    if (!token) return;

    const verify = async () => {
      try {
        await axios.post(`${API_URL}/auth/verify-email`, { token });
        setStatus("success");
        setTimeout(() => router.push("/login"), 3000);
      } catch (err) {
        setStatus("error");
        setErrorMsg(err.response?.data?.detail || t('auth:emailVerification.error'));
      }
    };
    verify();
  }, [token]);

  return (
    <div className="min-h-screen flex flex-col justify-center items-center bg-gray-50 p-4">

      <div className="bg-white p-8 rounded-card shadow-card w-full max-w-md border border-gray-100 animate-fade-in">
        {status === "loading" && (
          <div className="text-center space-y-4">
            <div className="inline-flex items-center justify-center w-16 h-16 rounded-full bg-gradient-to-br from-purple-100 to-blue-100 mb-4">
              <Loader2 className="w-8 h-8 text-purple-600 animate-spin" />
            </div>
            <h2 className="text-2xl font-heading font-bold text-gray-900">
              {t('auth:emailVerification.required')}
            </h2>
          </div>
        )}

        {status === "success" && (
          <div className="text-center space-y-4">
            <div className="inline-flex items-center justify-center w-16 h-16 rounded-full bg-gradient-to-br from-green-100 to-blue-100 mb-4">
              <CheckCircle2 className="w-8 h-8 text-green-600" />
            </div>
            <h2 className="text-2xl font-bold text-green-700">
              {t('auth:emailVerification.success')}
            </h2>
            <div className="flex items-center justify-center space-x-2 text-gray-600">
              <div className="animate-spin rounded-full h-5 w-5 border-b-2 border-blue-600"></div>
              <span className="font-medium">{t('auth:emailVerification.redirecting')}</span>
            </div>
          </div>
        )}

        {status === "error" && (
          <div className="text-center space-y-4">
            <div className="inline-flex items-center justify-center w-16 h-16 rounded-full bg-gradient-to-br from-red-100 to-pink-100 mb-4">
              <XCircle className="w-8 h-8 text-red-600" />
            </div>
            <h2 className="text-2xl font-bold text-red-700">
              {t('auth:emailVerification.expired')}
            </h2>
            <p className="text-gray-600">{errorMsg}</p>
            <button
              onClick={() => router.push('/login')}
              className="mt-4 inline-flex items-center px-6 py-3 bg-gradient-to-r from-blue-600 to-purple-600 text-white font-bold rounded-button shadow-card hover:shadow-elevated hover:from-blue-700 hover:to-purple-700 transition-all"
            >
              <ArrowRight className="w-5 h-5 mr-2" />
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
