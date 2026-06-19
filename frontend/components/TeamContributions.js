import { useState } from 'react';
import { useTranslation } from 'next-i18next';
import { ChevronDown, ChevronUp, Bot, Users } from 'lucide-react';
import MarkdownRenderer from './MarkdownRenderer';

/**
 * Collapsible accordion showing individual agent contributions
 * below the leader's synthesized response.
 *
 * Props:
 *   contributions: Array of { agent_id, agent_name, specialization, content }
 */
export default function TeamContributions({ contributions }) {
  const { t } = useTranslation('teams');
  const [open, setOpen] = useState(false);
  const [expandedCards, setExpandedCards] = useState({});

  if (!contributions || contributions.length === 0) return null;

  const toggleCard = (agentId) => {
    setExpandedCards(prev => ({ ...prev, [agentId]: !prev[agentId] }));
  };

  const count = contributions.length;

  return (
    <div className="mt-4">
      {/* Toggle button */}
      <button
        onClick={() => setOpen(!open)}
        className={`group flex items-center gap-2.5 px-4 py-2.5 rounded-full text-sm font-semibold transition-all duration-200 border ${
          open
            ? 'bg-blue-50 border-blue-200 text-blue-700 shadow-sm'
            : 'bg-gray-50 border-gray-200 text-gray-600 hover:bg-blue-50 hover:border-blue-200 hover:text-blue-700'
        }`}
      >
        <Users className="w-4 h-4" />
        <span>
          {t('chat.companionsUsed', { count })}
        </span>
        {/* Agent avatar stack */}
        <span className="flex -space-x-1.5 ml-1">
          {contributions.slice(0, 4).map((c, i) => (
            <span
              key={c.agent_id || i}
              className="inline-flex items-center justify-center w-5 h-5 rounded-full bg-gradient-to-br from-blue-500 to-purple-500 text-white text-[9px] font-bold ring-2 ring-white"
              title={c.agent_name}
            >
              {(c.agent_name || '?')[0].toUpperCase()}
            </span>
          ))}
          {count > 4 && (
            <span className="inline-flex items-center justify-center w-5 h-5 rounded-full bg-gray-300 text-gray-600 text-[9px] font-bold ring-2 ring-white">
              +{count - 4}
            </span>
          )}
        </span>
        {open ? (
          <ChevronUp className="w-3.5 h-3.5 ml-0.5 transition-transform" />
        ) : (
          <ChevronDown className="w-3.5 h-3.5 ml-0.5 transition-transform" />
        )}
      </button>

      {/* Expanded contributions */}
      {open && (
        <div className="mt-3 space-y-2.5 animate-fade-in">
          {contributions.map((c) => {
            const cardKey = c.agent_id || c.agent_name;
            const isExpanded = expandedCards[cardKey];
            const content = c.content || '';
            const isLong = content.length > 300;

            return (
              <div
                key={cardKey}
                className="rounded-lg border border-gray-200 bg-gray-50 overflow-hidden transition-all duration-200"
              >
                {/* Card header */}
                <div className="flex items-center gap-2.5 px-4 py-2.5">
                  <span className="inline-flex items-center justify-center w-6 h-6 rounded-full bg-gradient-to-br from-blue-500 to-purple-500 text-white text-xs font-bold shrink-0">
                    {(c.agent_name || '?')[0].toUpperCase()}
                  </span>
                  <span className="text-sm font-semibold text-gray-800 truncate">
                    {c.agent_name}
                  </span>
                  {c.specialization && (
                    <span className="px-2 py-0.5 text-[10px] font-bold rounded-full bg-blue-100 text-blue-700 shrink-0 truncate max-w-[160px]">
                      {c.specialization}
                    </span>
                  )}
                </div>

                {/* Card content */}
                <div className="px-4 pb-3">
                  <div
                    className={`text-sm text-gray-700 ${
                      !isExpanded && isLong ? 'line-clamp-4' : ''
                    }`}
                  >
                    <MarkdownRenderer variant="contribution">
                      {content}
                    </MarkdownRenderer>
                  </div>
                  {isLong && (
                    <button
                      onClick={() => toggleCard(cardKey)}
                      className="mt-1.5 text-xs font-medium text-blue-600 hover:text-blue-700 transition-colors flex items-center gap-1"
                    >
                      {isExpanded ? (
                        <><ChevronUp className="w-3 h-3" />{t('chat.collapse')}</>
                      ) : (
                        <><ChevronDown className="w-3 h-3" />{t('chat.expand')}</>
                      )}
                    </button>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
