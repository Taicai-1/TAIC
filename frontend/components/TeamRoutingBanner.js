import { useTranslation } from 'next-i18next';
import { Bot, CheckCircle, AlertCircle, Loader2 } from 'lucide-react';

/**
 * Animated banner showing which agents are being consulted.
 *
 * Props:
 *   agents: Array of { id, name, specialization, status }
 *     status: "pending" | "done" | "error"
 *   visible: boolean
 */
export default function TeamRoutingBanner({ agents, visible }) {
  const { t } = useTranslation('teams');

  if (!visible || !agents || agents.length === 0) return null;

  return (
    <div className="bg-gradient-to-r from-blue-50 to-indigo-50 border border-blue-200 rounded-lg p-4 mb-3 animate-in fade-in">
      <div className="flex items-center gap-2 mb-3 text-sm font-medium text-blue-700">
        <Loader2 className="w-4 h-4 animate-spin" />
        {t('chat.consultingAgents')}
      </div>
      <div className="flex flex-wrap gap-3">
        {agents.map((agent) => (
          <div
            key={agent.id}
            className={`flex items-center gap-2 px-3 py-2 rounded-md border text-sm transition-all ${
              agent.status === 'done'
                ? 'bg-green-50 border-green-200 text-green-700'
                : agent.status === 'error'
                ? 'bg-red-50 border-red-200 text-red-600'
                : 'bg-white border-blue-200 text-blue-600 animate-pulse'
            }`}
          >
            <Bot className="w-4 h-4" />
            <div>
              <div className="font-medium">{agent.name}</div>
              {agent.specialization && (
                <div className="text-xs opacity-70">{agent.specialization}</div>
              )}
            </div>
            {agent.status === 'done' && <CheckCircle className="w-4 h-4 text-green-500" />}
            {agent.status === 'error' && <AlertCircle className="w-4 h-4 text-red-500" />}
          </div>
        ))}
      </div>
    </div>
  );
}
