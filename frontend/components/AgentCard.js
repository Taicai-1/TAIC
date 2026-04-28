import { MessageCircle, Settings, Trash2, Share2, Users, TrendingUp, Image as ImageIcon } from 'lucide-react';
import { useTranslation } from 'next-i18next';
import { getApiUrl } from '../lib/api';

const TYPE_META = {
  conversationnel: { label: 'Conversationnel', Icon: Users,      color: 'text-primary-600',   bg: 'bg-primary-50',   stripe: 'bg-primary-600'  },
  recherche_live:  { label: 'Recherche Live',  Icon: TrendingUp, color: 'text-violet-600', bg: 'bg-violet-50', stripe: 'bg-violet-600' },
  visuel:          { label: 'Visuel',          Icon: ImageIcon,  color: 'text-pink-600',   bg: 'bg-pink-50',   stripe: 'bg-pink-600'   },
};

export default function AgentCard({ agent, onChat, onEdit, onDelete }) {
  const { t } = useTranslation('agents');
  const meta = TYPE_META[agent.type] || TYPE_META.conversationnel;
  const API = getApiUrl();

  return (
    <div className="group bg-white rounded-card border border-gray-200 hover:border-gray-300 hover:shadow-elevated transition-all duration-200 overflow-hidden">
      <div className={`h-1 w-full ${meta.stripe}`} />

      <div className="p-4">
        <div className="flex items-start justify-between mb-3">
          {agent.profile_photo ? (
            <div className="relative">
              <img
                src={`${API}/api/agent-photo/${agent.id}`}
                alt={agent.name}
                className="w-11 h-11 rounded-sm object-cover ring-2 ring-white shadow-card"
                onError={e => { e.target.onerror = null; e.target.src = '/default-avatar.svg'; }}
              />
              <div className="absolute -bottom-0.5 -right-0.5 w-3 h-3 bg-green-500 rounded-full border-2 border-white" />
            </div>
          ) : (
            <div className={`w-11 h-11 rounded-sm ${meta.bg} flex items-center justify-center`}>
              <meta.Icon className={`w-5 h-5 ${meta.color}`} />
            </div>
          )}

          <div className="flex gap-1.5 opacity-0 group-hover:opacity-100 transition-opacity">
            {(!agent.shared || agent.can_edit) && (
              <button onClick={onEdit} title={t('buttons.edit')}
                className="p-1.5 text-gray-400 hover:text-primary-600 hover:bg-primary-50 rounded-sm transition-colors">
                <Settings className="w-4 h-4" />
              </button>
            )}
            {!agent.shared && (
              <button onClick={onDelete} title={t('buttons.delete')}
                className="p-1.5 text-gray-400 hover:text-red-600 hover:bg-red-50 rounded-sm transition-colors">
                <Trash2 className="w-4 h-4" />
              </button>
            )}
          </div>
        </div>

        <p className="font-heading font-bold text-[15px] text-gray-900 mb-2 truncate group-hover:text-primary-600 transition-colors">
          {agent.name}
        </p>

        <div className="flex flex-wrap gap-1.5 mb-3">
          <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[11px] font-semibold ${meta.bg} ${meta.color}`}>
            <meta.Icon className="w-2.5 h-2.5" />
            {meta.label}
          </span>
          {agent.neo4j_enabled && (
            <span className="px-2 py-0.5 rounded-full text-[11px] font-semibold bg-teal-50 text-teal-700">Neo4j</span>
          )}
          {agent.shared && (
            <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[11px] font-semibold ${agent.can_edit ? 'bg-purple-50 text-purple-700' : 'bg-orange-50 text-orange-700'}`}>
              <Share2 className="w-2.5 h-2.5" />
              {agent.can_edit ? t('badges.sharedEdit') : t('badges.sharedReadOnly')}
            </span>
          )}
        </div>

        {agent.shared && agent.owner_username && (
          <p className="text-xs text-gray-400 mb-3">{t('badges.sharedBy', { owner: agent.owner_username })}</p>
        )}

        <button onClick={onChat}
          className="w-full flex items-center justify-center gap-2 py-2 bg-primary-600 hover:bg-primary-700 text-white text-sm font-semibold rounded-button transition-colors">
          <MessageCircle className="w-3.5 h-3.5" />
          {t('buttons.openCompanion')}
        </button>
      </div>
    </div>
  );
}
