import { useState, useCallback } from 'react';
import { useTranslation } from 'next-i18next';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { Prism as SyntaxHighlighter } from 'react-syntax-highlighter';
import { oneDark } from 'react-syntax-highlighter/dist/cjs/styles/prism';
import { Copy, Check } from 'lucide-react';

/**
 * Shared markdown renderer for all chat messages.
 *
 * Props:
 *   children  - markdown string to render
 *   variant   - "agent" (default) | "user" | "contribution"
 */

/* ── Image sub-component (relocated from [agentId].js) ── */
const MarkdownImage = ({ src, alt, t }) => (
  <div className="my-3">
    <img
      src={src}
      alt={alt}
      className="max-w-full rounded-button shadow-card border border-gray-200"
      style={{ maxHeight: '512px', objectFit: 'contain' }}
      loading="lazy"
    />
    <div className="flex gap-2 mt-2">
      <a
        href={src}
        download
        className="px-3 py-1.5 bg-primary-600 text-white rounded-sm hover:bg-primary-700 text-sm"
      >
        {t('chat:messages.downloadImage')}
      </a>
      <button
        className="px-3 py-1.5 bg-gray-200 text-gray-800 rounded-sm hover:bg-gray-300 text-sm"
        onClick={() => window.open(src, '_blank')}
      >
        {t('chat:messages.fullSize')}
      </button>
    </div>
  </div>
);

/* ── Code block with syntax highlighting + copy button ── */
const CodeBlock = ({ className, children }) => {
  const [copied, setCopied] = useState(false);
  const match = /language-(\w+)/.exec(className || '');
  const language = match ? match[1] : null;
  const codeString = String(children).replace(/\n$/, '');

  const handleCopy = useCallback(() => {
    navigator.clipboard?.writeText(codeString);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  }, [codeString]);

  return (
    <div className="relative group my-3">
      {language && (
        <span className="absolute top-2 left-3 text-[11px] text-gray-400 font-mono uppercase select-none">
          {language}
        </span>
      )}
      <button
        onClick={handleCopy}
        className="absolute top-2 right-2 flex items-center gap-1 px-2 py-1 rounded text-[11px] bg-white/10 border border-white/15 text-gray-400 hover:bg-white/20 hover:text-gray-200 opacity-0 group-hover:opacity-100 transition-opacity"
      >
        {copied ? <Check className="w-3 h-3" /> : <Copy className="w-3 h-3" />}
        {copied ? 'Copié' : 'Copier'}
      </button>
      <SyntaxHighlighter
        style={oneDark}
        language={language || 'text'}
        PreTag="div"
        customStyle={{
          margin: 0,
          borderRadius: '8px',
          padding: language ? '2.25rem 1.25rem 1rem' : '1rem 1.25rem',
          fontSize: '0.825rem',
          lineHeight: '1.6',
        }}
      >
        {codeString}
      </SyntaxHighlighter>
    </div>
  );
};

/* ── Main component ── */
export default function MarkdownRenderer({ children, variant = 'agent' }) {
  const { t } = useTranslation(['chat']);

  if (!children) return null;

  const isUser = variant === 'user';

  /* Build component overrides based on variant */
  const components = {
    /* ── Headings ── */
    h1: ({ node, ...props }) => <h1 className={isUser ? 'text-white' : ''} {...props} />,
    h2: ({ node, ...props }) => <h2 className={isUser ? 'text-white border-white/20' : ''} {...props} />,
    h3: ({ node, ...props }) => <h3 className={isUser ? 'text-white' : ''} {...props} />,
    h4: ({ node, ...props }) => <h4 className={isUser ? 'text-white' : ''} {...props} />,

    /* ── Text ── */
    p: ({ node, ...props }) => (
      <p className={isUser ? 'text-white mb-2 last:mb-0' : 'mb-2 last:mb-0'} {...props} />
    ),
    strong: ({ node, ...props }) => (
      <strong className={isUser ? 'text-white font-bold' : 'font-bold'} {...props} />
    ),
    em: ({ node, ...props }) => (
      <em className={isUser ? 'text-white/90 italic' : 'italic'} {...props} />
    ),

    /* ── Lists ── */
    ul: ({ node, ...props }) => (
      <ul className={`list-disc pl-6 mb-2 ${isUser ? 'text-white' : ''}`} {...props} />
    ),
    ol: ({ node, ...props }) => (
      <ol className={`list-decimal pl-6 mb-2 ${isUser ? 'text-white' : ''}`} {...props} />
    ),
    li: ({ node, ...props }) => <li className="mb-1" {...props} />,

    /* ── Blockquote ── */
    blockquote: ({ node, ...props }) => (
      <blockquote
        className={
          isUser
            ? 'border-l-3 border-white/40 bg-white/10 px-4 py-3 my-3 rounded-r-lg italic text-white/90'
            : ''
        }
        {...props}
      />
    ),

    /* ── Links ── */
    a: ({ node, ...props }) => (
      <a
        className={isUser ? 'text-blue-200 underline hover:text-blue-100' : ''}
        target="_blank"
        rel="noopener noreferrer"
        {...props}
      />
    ),

    /* ── Code: inline vs block ── */
    code: ({ node, inline, className, children, ...props }) => {
      if (!inline && /language-(\w+)/.test(className || '')) {
        return <CodeBlock className={className}>{children}</CodeBlock>;
      }
      if (!inline && String(children).includes('\n')) {
        return <CodeBlock className={className}>{children}</CodeBlock>;
      }
      return (
        <code
          className={
            isUser
              ? 'bg-white/20 text-white px-1.5 py-0.5 rounded text-[0.85em] font-mono'
              : ''
          }
          {...props}
        >
          {children}
        </code>
      );
    },

    /* ── Pre: delegate to code block ── */
    pre: ({ node, children, ...props }) => <>{children}</>,

    /* ── Tables ── */
    table: ({ node, ...props }) => (
      <div className="overflow-x-auto my-3 border border-gray-200 rounded-lg">
        <table className="min-w-full border-collapse text-sm" {...props} />
      </div>
    ),
    thead: ({ node, ...props }) => (
      <thead className={isUser ? 'bg-white/10' : 'bg-gray-50'} {...props} />
    ),
    th: ({ node, ...props }) => (
      <th
        className={
          isUser
            ? 'border-b border-white/20 px-3 py-2 text-left font-semibold text-white'
            : 'border-b-2 border-gray-200 px-3 py-2.5 text-left font-semibold text-gray-700'
        }
        {...props}
      />
    ),
    td: ({ node, ...props }) => (
      <td
        className={
          isUser
            ? 'border-b border-white/10 px-3 py-2 text-white/90'
            : 'border-b border-gray-100 px-3 py-2.5 text-gray-600'
        }
        {...props}
      />
    ),
    tr: ({ node, ...props }) => (
      <tr className={isUser ? '' : 'even:bg-gray-50/50 hover:bg-gray-50'} {...props} />
    ),

    /* ── Images ── */
    img: ({ node, ...props }) => <MarkdownImage {...props} t={t} />,
  };

  const proseClasses = isUser
    ? 'prose prose-sm prose-invert max-w-none'
    : variant === 'contribution'
      ? 'prose prose-sm max-w-none'
      : 'prose prose-sm max-w-none';

  return (
    <div className={proseClasses}>
      <ReactMarkdown remarkPlugins={[remarkGfm]} components={components}>
        {children}
      </ReactMarkdown>
    </div>
  );
}
