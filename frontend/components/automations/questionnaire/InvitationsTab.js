import { useState, useEffect, useCallback } from 'react';
import { useTranslation } from 'next-i18next';
import toast from 'react-hot-toast';
import { Send, RefreshCw, AlertTriangle } from 'lucide-react';
import api from '../../../lib/api';
import { STATUS_BADGE_CLASSES } from './constants';

const EMAIL_RE = /^[^@\s]+@[^@\s]+\.[^@\s]+$/;

function parseRecipients(raw) {
  return raw
    .split(/[\n;]+/)
    .map((line) => line.trim())
    .filter(Boolean)
    .map((line) => {
      const [email, ...nameParts] = line.split(',').map((s) => s.trim());
      return { email: email.toLowerCase(), name: nameParts.join(', ') || null };
    })
    .filter((r) => EMAIL_RE.test(r.email));
}

export default function InvitationsTab({ questionnaireId }) {
  const { t } = useTranslation('automations');
  const [raw, setRaw] = useState('');
  const [sending, setSending] = useState(false);
  const [invitations, setInvitations] = useState([]);

  const load = useCallback(async () => {
    try {
      const res = await api.get(
        `/api/automations/questionnaires/${questionnaireId}/responses?limit=200`
      );
      setInvitations(res.data.responses || []);
    } catch {
      toast.error(t('errors.loadFailed'));
    }
  }, [questionnaireId, t]);

  useEffect(() => {
    load();
  }, [load]);

  const send = async () => {
    const recipients = parseRecipients(raw);
    if (!recipients.length) {
      toast.error(t('invitations.noEmails'));
      return;
    }
    setSending(true);
    try {
      const res = await api.post(
        `/api/automations/questionnaires/${questionnaireId}/invite`,
        { recipients }
      );
      toast.success(t('invitations.sent', { count: res.data.invited }));
      if (res.data.skipped > 0) {
        toast(t('invitations.skipped', { count: res.data.skipped }));
      }
      setRaw('');
      load();
    } catch (err) {
      const detail = err.response?.data?.detail;
      toast.error(typeof detail === 'string' ? detail : t('errors.saveFailed'));
    } finally {
      setSending(false);
    }
  };

  const resend = async (responseId) => {
    try {
      await api.post(
        `/api/automations/questionnaires/${questionnaireId}/responses/${responseId}/resend`
      );
      toast.success(t('invitations.resent'));
      load();
    } catch {
      toast.error(t('errors.saveFailed'));
    }
  };

  return (
    <div className="space-y-8">
      <div>
        <h3 className="text-sm font-semibold text-gray-800 mb-1">{t('invitations.title')}</h3>
        <p className="text-xs text-gray-400 mb-3">{t('invitations.hint')}</p>
        <textarea
          value={raw}
          onChange={(e) => setRaw(e.target.value)}
          placeholder={t('invitations.placeholder')}
          rows={4}
          className="w-full px-3 py-2 border border-gray-200 rounded-input text-sm focus:ring-2 focus:ring-primary-500 focus:border-primary-500"
        />
        <button
          onClick={send}
          disabled={sending}
          className="mt-3 flex items-center gap-2 px-4 py-2 bg-primary-600 text-white text-sm font-semibold rounded-button hover:bg-primary-700 transition-colors disabled:opacity-50"
        >
          <Send className="w-4 h-4" />
          {t('invitations.send')}
        </button>
      </div>

      <div>
        <h3 className="text-sm font-semibold text-gray-800 mb-3">{t('invitations.listTitle')}</h3>
        {invitations.length === 0 ? (
          <p className="text-sm text-gray-400">{t('invitations.empty')}</p>
        ) : (
          <div className="border border-gray-200 rounded-card divide-y divide-gray-100 bg-white">
            {invitations.map((inv) => (
              <div key={inv.id} className="flex items-center gap-3 px-4 py-3">
                <div className="flex-1 min-w-0">
                  <p className="text-sm text-gray-800 truncate">{inv.respondent_email}</p>
                  {inv.respondent_name && (
                    <p className="text-xs text-gray-400">{inv.respondent_name}</p>
                  )}
                </div>
                {!inv.email_sent && inv.status === 'pending' && (
                  <span
                    className="flex items-center gap-1 text-xs text-amber-600"
                    title={t('invitations.emailFailed')}
                  >
                    <AlertTriangle className="w-3.5 h-3.5" />
                    {t('invitations.emailFailed')}
                  </span>
                )}
                <span
                  className={`text-xs px-2 py-0.5 rounded-full font-medium ${STATUS_BADGE_CLASSES[inv.status] || 'bg-gray-50 text-gray-600'}`}
                >
                  {t(`invitations.status.${inv.status}`)}
                </span>
                {inv.status === 'pending' && (
                  <button
                    onClick={() => resend(inv.id)}
                    className="flex items-center gap-1 text-xs text-primary-600 hover:text-primary-700 font-medium"
                  >
                    <RefreshCw className="w-3.5 h-3.5" />
                    {t('invitations.resend')}
                  </button>
                )}
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
