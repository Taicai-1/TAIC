import { useState, useEffect } from 'react';
import { useTranslation } from 'next-i18next';
import { Send, Plus, Mail, X, Clock, CheckCircle, Loader2 } from 'lucide-react';
import api from '../../lib/api';
import toast from 'react-hot-toast';

const STATUS_COLORS = {
  pending: 'bg-yellow-100 text-yellow-700',
  in_progress: 'bg-blue-100 text-blue-700',
  completed: 'bg-green-100 text-green-700',
};

export default function InvitationsTab({ agentId }) {
  const { t } = useTranslation('questionnaire');
  const [responses, setResponses] = useState([]);
  const [stats, setStats] = useState({ total_invited: 0, total_completed: 0 });
  const [newEmails, setNewEmails] = useState([{ email: '', name: '' }]);
  const [sending, setSending] = useState(false);

  useEffect(() => {
    if (agentId) loadResponses();
  }, [agentId]);

  const loadResponses = async () => {
    try {
      const res = await api.get(`/api/agents/${agentId}/responses`);
      setResponses(res.data.responses);
      setStats({ total_invited: res.data.total_invited, total_completed: res.data.total_completed });
    } catch (err) {
      console.error('Failed to load responses:', err);
    }
  };

  const addEmailRow = () => {
    setNewEmails([...newEmails, { email: '', name: '' }]);
  };

  const removeEmailRow = (idx) => {
    setNewEmails(newEmails.filter((_, i) => i !== idx));
  };

  const updateEmailRow = (idx, field, value) => {
    const next = [...newEmails];
    next[idx] = { ...next[idx], [field]: value };
    setNewEmails(next);
  };

  const sendInvitations = async () => {
    const validEmails = newEmails.filter(e => e.email.trim());
    if (validEmails.length === 0) return;

    setSending(true);
    try {
      const res = await api.post(`/api/agents/${agentId}/invite`, {
        emails: validEmails.map(e => e.email.trim()),
        names: validEmails.map(e => e.name.trim() || null),
      });
      toast.success(t('invitations.sent', { count: res.data.invited }));
      setNewEmails([{ email: '', name: '' }]);
      loadResponses();
    } catch (err) {
      toast.error('Failed to send invitations');
    } finally {
      setSending(false);
    }
  };

  return (
    <div className="space-y-6">
      {/* Add new invitations */}
      <div className="bg-white border border-gray-200 rounded-card p-5">
        <h3 className="text-sm font-semibold text-gray-800 mb-4 flex items-center gap-2">
          <Mail className="w-4 h-4 text-primary-600" />
          {t('invitations.title')}
        </h3>
        <div className="space-y-2">
          {newEmails.map((row, idx) => (
            <div key={idx} className="flex items-center gap-2">
              <input
                type="email"
                value={row.email}
                onChange={(e) => updateEmailRow(idx, 'email', e.target.value)}
                placeholder={t('invitations.emailPlaceholder')}
                className="flex-1 px-3 py-2 border border-gray-200 rounded-input text-sm focus:ring-2 focus:ring-primary-500"
              />
              <input
                type="text"
                value={row.name}
                onChange={(e) => updateEmailRow(idx, 'name', e.target.value)}
                placeholder={t('invitations.namePlaceholder')}
                className="w-40 px-3 py-2 border border-gray-200 rounded-input text-sm focus:ring-2 focus:ring-primary-500"
              />
              {newEmails.length > 1 && (
                <button onClick={() => removeEmailRow(idx)} className="p-1 text-gray-400 hover:text-red-500">
                  <X className="w-4 h-4" />
                </button>
              )}
            </div>
          ))}
        </div>
        <div className="flex items-center gap-3 mt-3">
          <button onClick={addEmailRow} className="flex items-center gap-1 text-sm text-gray-600 hover:text-gray-800">
            <Plus className="w-3.5 h-3.5" />
            {t('invitations.addEmail')}
          </button>
          <button
            onClick={sendInvitations}
            disabled={sending || !newEmails.some(e => e.email.trim())}
            className="ml-auto flex items-center gap-2 px-4 py-2 bg-primary-600 text-white rounded-button text-sm font-medium hover:bg-primary-700 disabled:opacity-50 transition-colors"
          >
            {sending ? <Loader2 className="w-4 h-4 animate-spin" /> : <Send className="w-4 h-4" />}
            {t('invitations.send')}
          </button>
        </div>
      </div>

      {/* Invitation list */}
      {responses.length > 0 && (
        <div className="bg-white border border-gray-200 rounded-card overflow-hidden">
          <div className="px-5 py-3 border-b border-gray-100 bg-gray-50">
            <p className="text-sm text-gray-600">
              {t('responses.counter', { completed: stats.total_completed, total: stats.total_invited })}
            </p>
          </div>
          <div className="divide-y divide-gray-100">
            {responses.map((r) => (
              <div key={r.id} className="flex items-center px-5 py-3">
                <div className="flex-1 min-w-0">
                  <p className="text-sm font-medium text-gray-800 truncate">{r.respondent_name || r.respondent_email}</p>
                  {r.respondent_name && <p className="text-xs text-gray-500">{r.respondent_email}</p>}
                </div>
                <span className={`px-2.5 py-0.5 text-xs font-medium rounded-full ${STATUS_COLORS[r.status]}`}>
                  {t(`invitations.status.${r.status}`)}
                </span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
