import { useState } from 'react';
import { useTranslation } from 'next-i18next';
import { ChevronDown, ChevronUp, Bot } from 'lucide-react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';

/**
 * Collapsible accordion showing individual agent contributions.
 *
 * Props:
 *   contributions: Array of { agent_id, agent_name, specialization, content }
 */
export default function TeamContributions({ contributions }) {
  const { t } = useTranslation('teams');
  const [open, setOpen] = useState(false);

  if (!contributions || contributions.length === 0) return null;

  const label = contributions.length === 1
    ? t('chat.contribution')
    : t('chat.contributions');

  return (
    <div className="mt-3 border border-gray-200 rounded-lg overflow-hidden">
      <button
        onClick={() => setOpen(!open)}
        className="w-full flex items-center justify-between px-4 py-2 bg-gray-50 hover:bg-gray-100 transition-colors text-sm font-medium text-gray-600"
      >
        <span>{label} ({contributions.length})</span>
        {open ? <ChevronUp className="w-4 h-4" /> : <ChevronDown className="w-4 h-4" />}
      </button>
      {open && (
        <div className="divide-y divide-gray-100">
          {contributions.map((c) => (
            <div key={c.agent_id} className="px-4 py-3">
              <div className="flex items-center gap-2 mb-2">
                <Bot className="w-4 h-4 text-blue-500" />
                <span className="font-medium text-sm text-gray-800">{c.agent_name}</span>
                {c.specialization && (
                  <span className="text-xs text-gray-500 bg-gray-100 px-2 py-0.5 rounded-full">
                    {c.specialization}
                  </span>
                )}
              </div>
              <div className="text-sm text-gray-700 prose prose-sm max-w-none">
                <ReactMarkdown remarkPlugins={[remarkGfm]}>
                  {c.content}
                </ReactMarkdown>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
