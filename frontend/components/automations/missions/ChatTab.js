import { useState } from 'react';
import { useTranslation } from 'next-i18next';
import toast from 'react-hot-toast';
import { Send } from 'lucide-react';
import api from '../../../lib/api';
import MarkdownRenderer from '../../MarkdownRenderer';

export default function ChatTab({ missionId, hasCompanion }) {
  const { t } = useTranslation('automations');
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState('');
  const [conversationId, setConversationId] = useState(null);
  const [sending, setSending] = useState(false);

  const send = async () => {
    const text = input.trim();
    if (!text) return;
    setMessages((m) => [...m, { role: 'user', content: text }]);
    setInput('');
    setSending(true);
    try {
      const res = await api.post(`/api/automations/missions/${missionId}/chat`, {
        message: text,
        conversation_id: conversationId,
      });
      setConversationId(res.data.conversation_id);
      setMessages((m) => [...m, { role: 'agent', content: res.data.answer }]);
    } catch {
      toast.error(t('errors.saveFailed'));
    } finally {
      setSending(false);
    }
  };

  if (!hasCompanion) {
    return <p className="text-sm text-amber-600 py-8 text-center">{t('missions.chat.noCompanion')}</p>;
  }

  return (
    <div className="flex flex-col h-[60vh]">
      <div className="flex-1 overflow-y-auto space-y-3 mb-4">
        {messages.length === 0 ? (
          <p className="text-sm text-gray-400 py-8 text-center">{t('missions.chat.empty')}</p>
        ) : (
          messages.map((m, i) => (
            <div
              key={i}
              className={`max-w-[80%] px-4 py-2 rounded-card text-sm ${
                m.role === 'user'
                  ? 'ml-auto bg-primary-600 text-white'
                  : 'mr-auto bg-gray-100 text-gray-800'
              }`}
            >
              {m.role === 'agent' ? <MarkdownRenderer>{m.content}</MarkdownRenderer> : m.content}
            </div>
          ))
        )}
      </div>
      <div className="flex gap-2">
        <input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && !sending && send()}
          placeholder={t('missions.chat.placeholder')}
          className="flex-1 px-3 py-2 border border-gray-300 rounded-button text-sm focus:border-primary-500 focus:outline-none"
        />
        <button
          onClick={send}
          disabled={sending}
          className="flex items-center gap-2 px-4 py-2 bg-primary-600 text-white text-sm font-semibold rounded-button hover:bg-primary-700 disabled:opacity-50"
        >
          <Send className="w-4 h-4" />
          {t('missions.chat.send')}
        </button>
      </div>
    </div>
  );
}
