import { useState, useEffect } from 'react';
import { useRouter } from 'next/router';
import { useTranslation } from 'next-i18next';
import { serverSideTranslations } from 'next-i18next/serverSideTranslations';
import toast, { Toaster } from 'react-hot-toast';
import { Building2, Loader2, CheckCircle, XCircle } from 'lucide-react';

const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8080';

export default function JoinOrganization() {
  const router = useRouter();
  const { t } = useTranslation(['organization', 'common']);
  const { token: inviteToken, code: inviteCode } = router.query;

  const [status, setStatus] = useState('loading'); // loading | success | error | login_required
  const [message, setMessage] = useState('');
  const [companyName, setCompanyName] = useState('');

  useEffect(() => {
    if (!router.isReady) return;

    const authToken = localStorage.getItem('token');
    const tokenParam = inviteToken || '';
    const codeParam = inviteCode || '';

    if (!tokenParam && !codeParam) {
      setStatus('error');
      setMessage('No invitation token or code provided.');
      return;
    }

    if (!authToken) {
      // Store the invite info and redirect to login
      if (tokenParam) sessionStorage.setItem('pending_invite_token', tokenParam);
      if (codeParam) sessionStorage.setItem('pending_invite_code', codeParam);
      setStatus('login_required');
      setTimeout(() => router.push('/login'), 2000);
      return;
    }

    // Attempt to join
    joinOrganization(authToken, tokenParam, codeParam);
  }, [router.isReady, inviteToken, inviteCode]);

  // Also check on mount if there's a pending invite from a previous redirect
  useEffect(() => {
    const authToken = localStorage.getItem('token');
    if (!authToken) return;

    const pendingToken = sessionStorage.getItem('pending_invite_token');
    const pendingCode = sessionStorage.getItem('pending_invite_code');

    if (pendingToken || pendingCode) {
      sessionStorage.removeItem('pending_invite_token');
      sessionStorage.removeItem('pending_invite_code');
      joinOrganization(authToken, pendingToken || '', pendingCode || '');
    }
  }, []);

  const joinOrganization = async (authToken, tokenParam, codeParam) => {
    setStatus('loading');
    try {
      const body = {};
      if (tokenParam) body.token = tokenParam;
      if (codeParam) body.invite_code = codeParam;

      const res = await fetch(`${API_URL}/api/companies/join`, {
        method: 'POST',
        headers: { Authorization: `Bearer ${authToken}`, 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });

      if (res.ok) {
        const data = await res.json();
        setStatus('success');
        setCompanyName(data.company?.name || '');
        setMessage(data.message);
        setTimeout(() => router.push('/organization'), 3000);
      } else {
        const err = await res.json();
        setStatus('error');
        setMessage(err.detail || t('organization:errors.generic'));
      }
    } catch {
      setStatus('error');
      setMessage(t('organization:errors.generic'));
    }
  };

  return (
    <div className="min-h-screen flex items-center justify-center bg-gray-50">
      <Toaster position="top-right" />

      <div className="max-w-md w-full mx-4">
        <div className="bg-white rounded-card shadow-card border border-gray-100 p-8 text-center">
          {status === 'loading' && (
            <>
              <Loader2 className="w-16 h-16 text-blue-600 animate-spin mx-auto mb-4" />
              <h2 className="text-xl font-bold text-gray-900 mb-2">Joining organization...</h2>
            </>
          )}

          {status === 'success' && (
            <>
              <div className="w-16 h-16 rounded-full bg-green-100 flex items-center justify-center mx-auto mb-4">
                <CheckCircle className="w-10 h-10 text-green-600" />
              </div>
              <h2 className="text-xl font-bold text-gray-900 mb-2">{message}</h2>
              {companyName && (
                <div className="flex items-center justify-center space-x-2 mb-4">
                  <Building2 className="w-5 h-5 text-teal-600" />
                  <span className="font-semibold text-teal-800">{companyName}</span>
                </div>
              )}
              <p className="text-sm text-gray-500">Redirecting to organization page...</p>
            </>
          )}

          {status === 'error' && (
            <>
              <div className="w-16 h-16 rounded-full bg-red-100 flex items-center justify-center mx-auto mb-4">
                <XCircle className="w-10 h-10 text-red-600" />
              </div>
              <h2 className="text-xl font-bold text-gray-900 mb-2">Unable to join</h2>
              <p className="text-gray-600 mb-4">{message}</p>
              <button onClick={() => router.push('/agents')}
                className="px-6 py-2 bg-blue-600 hover:bg-blue-700 text-white font-medium rounded-button transition-colors shadow-card hover:shadow-elevated">
                Go to dashboard
              </button>
            </>
          )}

          {status === 'login_required' && (
            <>
              <div className="w-16 h-16 rounded-full bg-blue-100 flex items-center justify-center mx-auto mb-4">
                <Building2 className="w-10 h-10 text-blue-600" />
              </div>
              <h2 className="text-xl font-bold text-gray-900 mb-2">Login required</h2>
              <p className="text-gray-600 mb-4">Please log in to accept this invitation. Redirecting...</p>
            </>
          )}
        </div>
      </div>
    </div>
  );
}

export async function getServerSideProps({ locale }) {
  return {
    props: {
      ...(await serverSideTranslations(locale, ['organization', 'common', 'errors'])),
    },
  };
}
