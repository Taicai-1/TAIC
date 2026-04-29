import { useState, useEffect, useCallback } from 'react';
import { useRouter } from 'next/router';
import { serverSideTranslations } from 'next-i18next/serverSideTranslations';
import { useAuth } from '../../hooks/useAuth';
import api from '../../lib/api';
import Layout from '../../components/Layout';
import {
  Activity,
  GitBranch,
  Shield,
  DollarSign,
  CheckCircle,
  AlertTriangle,
  XCircle,
  RefreshCw,
  ChevronDown,
  ChevronUp,
  Clock,
  Loader2,
} from 'lucide-react';

const ROUTINE_META = {
  health:   { label: 'Health',    icon: Activity,   bg: 'bg-blue-100',   text: 'text-blue-600' },
  ci_cd:    { label: 'CI/CD',     icon: GitBranch,  bg: 'bg-purple-100', text: 'text-purple-600' },
  security: { label: 'Security',  icon: Shield,     bg: 'bg-orange-100', text: 'text-orange-600' },
  billing:  { label: 'Billing',   icon: DollarSign,  bg: 'bg-green-100',  text: 'text-green-600' },
};

const STATUS_STYLES = {
  pass: { bg: 'bg-green-50', border: 'border-green-200', text: 'text-green-700', icon: CheckCircle },
  warn: { bg: 'bg-yellow-50', border: 'border-yellow-200', text: 'text-yellow-700', icon: AlertTriangle },
  fail: { bg: 'bg-red-50', border: 'border-red-200', text: 'text-red-700', icon: XCircle },
};

function StatusBadge({ status }) {
  const style = STATUS_STYLES[status] || STATUS_STYLES.warn;
  const Icon = style.icon;
  return (
    <span className={`inline-flex items-center gap-1 px-2 py-1 rounded-full text-xs font-medium ${style.bg} ${style.text}`}>
      <Icon className="w-3 h-3" />
      {status.toUpperCase()}
    </span>
  );
}

function TimeAgo({ dateStr }) {
  if (!dateStr) return <span className="text-gray-400 text-xs">Never</span>;
  const date = new Date(dateStr);
  const now = new Date();
  const diffMs = now - date;
  const diffMin = Math.floor(diffMs / 60000);
  const diffH = Math.floor(diffMin / 60);
  const diffD = Math.floor(diffH / 24);

  let text;
  if (diffMin < 1) text = 'just now';
  else if (diffMin < 60) text = `${diffMin}m ago`;
  else if (diffH < 24) text = `${diffH}h ago`;
  else text = `${diffD}d ago`;

  return <span className="text-gray-500 text-xs flex items-center gap-1"><Clock className="w-3 h-3" />{text}</span>;
}

function RoutineCard({ report, onExpand, expanded }) {
  const type = report?.type || 'health';
  const meta = ROUTINE_META[type] || ROUTINE_META.health;
  const Icon = meta.icon;
  const status = report?.status || 'warn';
  const checks = report?.data?.checks || [];
  const passCount = checks.filter(c => c.status === 'pass').length;
  const warnCount = checks.filter(c => c.status === 'warn').length;
  const failCount = checks.filter(c => c.status === 'fail').length;

  return (
    <div className={`rounded-lg border ${STATUS_STYLES[status]?.border || 'border-gray-200'} ${STATUS_STYLES[status]?.bg || 'bg-gray-50'} p-4`}>
      <div className="flex items-center justify-between cursor-pointer" onClick={onExpand}>
        <div className="flex items-center gap-3">
          <div className={`p-2 rounded-lg ${meta.bg}`}>
            <Icon className={`w-5 h-5 ${meta.text}`} />
          </div>
          <div>
            <h3 className="font-semibold text-gray-900">{meta.label}</h3>
            <TimeAgo dateStr={report?.created_at} />
          </div>
        </div>
        <div className="flex items-center gap-3">
          <StatusBadge status={status} />
          <span className="text-xs text-gray-500">{passCount}P {warnCount}W {failCount}F</span>
          {expanded ? <ChevronUp className="w-4 h-4 text-gray-400" /> : <ChevronDown className="w-4 h-4 text-gray-400" />}
        </div>
      </div>

      {expanded && checks.length > 0 && (
        <div className="mt-4 space-y-2 border-t border-gray-200 pt-3">
          {checks.map((check, i) => (
            <div key={i} className="flex items-center justify-between text-sm">
              <span className="text-gray-700 font-mono">{check.name}</span>
              <div className="flex items-center gap-2">
                <span className="text-gray-500 text-xs">{check.detail}</span>
                <StatusBadge status={check.status} />
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

export default function AdminMonitoring() {
  const { user, loading: authLoading, authenticated } = useAuth();
  const router = useRouter();
  const [reports, setReports] = useState([]);
  const [history, setHistory] = useState([]);
  const [historyTotal, setHistoryTotal] = useState(0);
  const [historyPage, setHistoryPage] = useState(1);
  const [loading, setLoading] = useState(true);
  const [running, setRunning] = useState(false);
  const [expanded, setExpanded] = useState({});
  const [error, setError] = useState(null);
  const [success, setSuccess] = useState(null);

  const loadLatest = useCallback(async () => {
    try {
      const res = await api.get('/api/admin/routine/latest');
      setReports(res.data.reports || []);
    } catch (err) {
      console.error('Failed to load latest reports:', err);
    }
  }, []);

  const loadHistory = useCallback(async (page = 1) => {
    try {
      const res = await api.get('/api/admin/routine/reports', { params: { page, page_size: 10 } });
      setHistory(res.data.reports || []);
      setHistoryTotal(res.data.total || 0);
      setHistoryPage(page);
    } catch (err) {
      console.error('Failed to load history:', err);
    }
  }, []);

  useEffect(() => {
    if (!authLoading && !authenticated) {
      router.push('/login');
      return;
    }
    if (authenticated) {
      setLoading(true);
      Promise.all([loadLatest(), loadHistory()]).finally(() => setLoading(false));
    }
  }, [authLoading, authenticated, loadLatest, loadHistory, router]);

  const handleRunAll = async () => {
    setRunning(true);
    setError(null);
    setSuccess(null);
    try {
      const res = await api.post('/api/admin/routine/run-all');
      await Promise.all([loadLatest(), loadHistory()]);
      const reports = res.data?.reports || [];
      const failCount = reports.filter(r => r.status === 'fail').length;
      const warnCount = reports.filter(r => r.status === 'warn').length;
      if (failCount > 0) {
        setError(`${reports.length} routines executed — ${failCount} failed, ${warnCount} warnings`);
      } else {
        setSuccess(`${reports.length} routines executed successfully${warnCount > 0 ? ` (${warnCount} warnings)` : ''}`);
      }
    } catch (err) {
      console.error('Run all failed:', err);
      const msg = err.response?.data?.detail || err.message || 'Unknown error';
      setError(`Failed to run routines: ${msg}`);
    } finally {
      setRunning(false);
      setTimeout(() => { setSuccess(null); }, 8000);
    }
  };

  const toggleExpand = (type) => {
    setExpanded(prev => ({ ...prev, [type]: !prev[type] }));
  };

  if (authLoading || loading) {
    return (
      <Layout>
        <div className="flex items-center justify-center min-h-[60vh]">
          <Loader2 className="w-8 h-8 animate-spin text-blue-500" />
        </div>
      </Layout>
    );
  }

  const orderedTypes = ['health', 'ci_cd', 'security', 'billing'];
  const reportsByType = {};
  reports.forEach(r => { reportsByType[r.type] = r; });

  return (
    <Layout>
      <div className="max-w-5xl mx-auto px-4 py-8">
        <div className="flex items-center justify-between mb-6">
          <div>
            <h1 className="text-2xl font-bold text-gray-900">Monitoring Dashboard</h1>
            <p className="text-gray-500 text-sm mt-1">Daily automated health checks</p>
          </div>
          <button
            onClick={handleRunAll}
            disabled={running}
            className="flex items-center gap-2 px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50 transition-colors"
          >
            <RefreshCw className={`w-4 h-4 ${running ? 'animate-spin' : ''}`} />
            {running ? 'Running...' : 'Run Now'}
          </button>
        </div>

        {/* Feedback banners */}
        {error && (
          <div className="mb-4 p-3 rounded-lg bg-red-50 border border-red-200 text-red-700 text-sm flex items-center justify-between">
            <div className="flex items-center gap-2">
              <XCircle className="w-4 h-4 flex-shrink-0" />
              <span>{error}</span>
            </div>
            <button onClick={() => setError(null)} className="text-red-400 hover:text-red-600">&times;</button>
          </div>
        )}
        {success && (
          <div className="mb-4 p-3 rounded-lg bg-green-50 border border-green-200 text-green-700 text-sm flex items-center justify-between">
            <div className="flex items-center gap-2">
              <CheckCircle className="w-4 h-4 flex-shrink-0" />
              <span>{success}</span>
            </div>
            <button onClick={() => setSuccess(null)} className="text-green-400 hover:text-green-600">&times;</button>
          </div>
        )}

        {/* Status cards */}
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mb-8">
          {orderedTypes.map(type => (
            <RoutineCard
              key={type}
              report={reportsByType[type] || { type, status: 'warn', data: { checks: [] } }}
              expanded={!!expanded[type]}
              onExpand={() => toggleExpand(type)}
            />
          ))}
        </div>

        {/* History table */}
        <div className="bg-white rounded-lg border border-gray-200">
          <div className="px-4 py-3 border-b border-gray-200">
            <h2 className="font-semibold text-gray-900">History</h2>
          </div>
          <div className="divide-y divide-gray-100">
            {history.length === 0 ? (
              <div className="px-4 py-8 text-center text-gray-400">No reports yet. Click &quot;Run Now&quot; to generate the first report.</div>
            ) : (
              history.map(report => (
                <div key={report.id} className="px-4 py-3 flex items-center justify-between hover:bg-gray-50">
                  <div className="flex items-center gap-3">
                    <StatusBadge status={report.status} />
                    <span className="text-sm font-medium text-gray-700 capitalize">{report.type.replace('_', '/')}</span>
                  </div>
                  <div className="flex items-center gap-4">
                    <span className="text-sm text-gray-500">{report.summary}</span>
                    <TimeAgo dateStr={report.created_at} />
                  </div>
                </div>
              ))
            )}
          </div>
          {historyTotal > 10 && (
            <div className="px-4 py-3 border-t border-gray-200 flex justify-between">
              <button
                onClick={() => loadHistory(historyPage - 1)}
                disabled={historyPage <= 1}
                className="text-sm text-blue-600 hover:text-blue-800 disabled:text-gray-300"
              >
                Previous
              </button>
              <span className="text-sm text-gray-500">Page {historyPage} of {Math.ceil(historyTotal / 10)}</span>
              <button
                onClick={() => loadHistory(historyPage + 1)}
                disabled={historyPage >= Math.ceil(historyTotal / 10)}
                className="text-sm text-blue-600 hover:text-blue-800 disabled:text-gray-300"
              >
                Next
              </button>
            </div>
          )}
        </div>
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
