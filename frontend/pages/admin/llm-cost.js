import { useState, useEffect, useCallback } from 'react';
import { useRouter } from 'next/router';
import { serverSideTranslations } from 'next-i18next/serverSideTranslations';
import { useAuth } from '../../hooks/useAuth';
import api from '../../lib/api';
import Layout from '../../components/Layout';

export default function AdminLlmCost() {
  const { user, loading: authLoading, authenticated } = useAuth();
  const router = useRouter();
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await api.get('/api/admin/llm-usage');
      setData(res.data);
    } catch (err) {
      if (err?.response?.status === 403) {
        setError('Accès réservé au compte support.');
      } else {
        setError('Impossible de charger la consommation LLM.');
      }
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (!authLoading && !authenticated) {
      router.push('/login');
      return;
    }
    // Admin area is reserved for the platform support account.
    if (authenticated && user && !user.is_support) {
      router.push('/agents');
      return;
    }
    if (authenticated && user?.is_support) load();
  }, [authLoading, authenticated, user, load, router]);

  const fmtUsd = (n) => `$${Number(n ?? 0).toFixed(4)}`;

  // Don't render the admin shell until we know the user is the support account
  // (avoids flashing the admin page chrome before the redirect fires).
  if (authLoading || !authenticated || !user?.is_support) {
    return (
      <Layout>
        <div className="max-w-5xl mx-auto px-4 py-8">
          <p className="text-gray-500">Chargement…</p>
        </div>
      </Layout>
    );
  }

  return (
    <Layout>
      <div className="max-w-5xl mx-auto px-4 py-8">
        <div className="flex items-center justify-between mb-6">
          <h1 className="text-2xl font-bold text-gray-900">Consommation LLM</h1>
          <button
            onClick={load}
            disabled={loading}
            className="px-4 py-2 rounded-lg bg-primary-600 text-white text-sm font-medium hover:bg-primary-700 disabled:opacity-50"
          >
            Rafraîchir
          </button>
        </div>

        {loading && <p className="text-gray-500">Chargement…</p>}
        {error && <div className="p-4 rounded-lg bg-red-50 text-red-700 border border-red-200">{error}</div>}

        {data && !loading && !error && (
          <div className="space-y-6">
            <p className="text-sm text-gray-500">
              Mois : <span className="font-medium text-gray-700">{data.month}</span> · Périmètre :{' '}
              <span className="font-medium text-gray-700">
                {data.scope === 'platform' ? 'Toutes les entreprises' : `Mon entreprise (#${data.company_id})`}
              </span>
            </p>

            <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
              <div className="bg-white rounded-xl shadow p-5">
                <div className="text-xs uppercase text-gray-400">Coût ce mois</div>
                <div className="text-2xl font-bold text-gray-900">{fmtUsd(data.total_cost_usd)}</div>
              </div>
              <div className="bg-white rounded-xl shadow p-5">
                <div className="text-xs uppercase text-gray-400">Appels</div>
                <div className="text-2xl font-bold text-gray-900">{data.total_calls}</div>
              </div>
              <div className="bg-white rounded-xl shadow p-5">
                <div className="text-xs uppercase text-gray-400">Tokens (entrée / sortie)</div>
                <div className="text-lg font-semibold text-gray-900">
                  {data.total_prompt_tokens} / {data.total_completion_tokens}
                </div>
              </div>
            </div>

            <div className="bg-white rounded-xl shadow overflow-hidden">
              <div className="px-5 py-3 border-b text-sm font-semibold text-gray-700">Par modèle</div>
              <table className="w-full text-sm">
                <thead className="bg-gray-50 text-gray-500">
                  <tr>
                    <th className="text-left px-5 py-2">Fournisseur</th>
                    <th className="text-left px-5 py-2">Modèle</th>
                    <th className="text-right px-5 py-2">Coût</th>
                    <th className="text-right px-5 py-2">Appels</th>
                  </tr>
                </thead>
                <tbody>
                  {(data.by_model || []).map((m, i) => (
                    <tr key={i} className="border-t">
                      <td className="px-5 py-2">{m.provider}</td>
                      <td className="px-5 py-2">{m.model}</td>
                      <td className="px-5 py-2 text-right">{fmtUsd(m.cost_usd)}</td>
                      <td className="px-5 py-2 text-right">{m.calls}</td>
                    </tr>
                  ))}
                  {(!data.by_model || data.by_model.length === 0) && (
                    <tr>
                      <td colSpan={4} className="px-5 py-4 text-center text-gray-400">
                        Aucune consommation ce mois.
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>

            {data.by_company && (
              <div className="bg-white rounded-xl shadow overflow-hidden">
                <div className="px-5 py-3 border-b text-sm font-semibold text-gray-700">Par entreprise</div>
                <table className="w-full text-sm">
                  <thead className="bg-gray-50 text-gray-500">
                    <tr>
                      <th className="text-left px-5 py-2">Entreprise</th>
                      <th className="text-right px-5 py-2">Coût</th>
                      <th className="text-right px-5 py-2">Appels</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.by_company.map((c, i) => (
                      <tr key={i} className="border-t">
                        <td className="px-5 py-2">#{c.company_id ?? '—'}</td>
                        <td className="px-5 py-2 text-right">{fmtUsd(c.cost_usd)}</td>
                        <td className="px-5 py-2 text-right">{c.calls}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        )}
      </div>
    </Layout>
  );
}

export async function getStaticProps({ locale }) {
  return {
    props: {
      ...(await serverSideTranslations(locale ?? 'fr', ['common'])),
    },
  };
}
