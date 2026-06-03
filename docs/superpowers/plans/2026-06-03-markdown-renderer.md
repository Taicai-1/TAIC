# Unified MarkdownRenderer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace 3 duplicated ReactMarkdown configurations with one shared `MarkdownRenderer` component using `@tailwindcss/typography` + `react-syntax-highlighter`.

**Architecture:** A single `components/MarkdownRenderer.js` component wraps `ReactMarkdown` with `remark-gfm`, `@tailwindcss/typography` prose classes, and custom component overrides for all markdown elements. Code blocks use `react-syntax-highlighter` with the `oneDark` theme. A `variant` prop controls color adaptation for agent/user/contribution contexts.

**Tech Stack:** React 18, Next.js 14, react-markdown 9, remark-gfm 4, @tailwindcss/typography, react-syntax-highlighter, Tailwind CSS 3.

---

## File Structure

| File | Action | Responsibility |
|------|--------|---------------|
| `frontend/components/MarkdownRenderer.js` | Create | Shared markdown rendering with prose + syntax highlighting |
| `frontend/tailwind.config.js` | Modify | Add typography plugin + prose overrides |
| `frontend/styles/globals.css` | Modify | Remove `.markdown-content` section |
| `frontend/pages/chat/[agentId].js` | Modify | Replace `MarkdownText` with `MarkdownRenderer`, remove old components |
| `frontend/pages/chat/team/[id].js` | Modify | Replace inline ReactMarkdown with `MarkdownRenderer` |
| `frontend/components/TeamContributions.js` | Modify | Replace bare ReactMarkdown with `MarkdownRenderer` |

---

### Task 1: Install dependencies

**Files:**
- Modify: `frontend/package.json`

- [ ] **Step 1: Install the two new packages**

```bash
cd frontend && npm install @tailwindcss/typography react-syntax-highlighter
```

Expected: `package.json` updated with both new dependencies, `node_modules` installed, no errors.

- [ ] **Step 2: Commit**

```bash
git add frontend/package.json frontend/package-lock.json
git commit -m "deps: add @tailwindcss/typography and react-syntax-highlighter"
```

---

### Task 2: Configure Tailwind typography plugin

**Files:**
- Modify: `frontend/tailwind.config.js`

- [ ] **Step 1: Add the typography plugin and prose overrides**

In `frontend/tailwind.config.js`, add the plugin to the `plugins` array and add `typography` overrides in `theme.extend`:

```js
/** @type {import('tailwindcss').Config} */
module.exports = {
  content: [
    './pages/**/*.{js,ts,jsx,tsx,mdx}',
    './components/**/*.{js,ts,jsx,tsx,mdx}',
    './app/**/*.{js,ts,jsx,tsx,mdx}',
  ],
  theme: {
    extend: {
      fontFamily: {
        heading: ['Plus Jakarta Sans', 'system-ui', 'sans-serif'],
        body: ['Inter', 'system-ui', 'sans-serif'],
      },
      colors: {
        primary: {
          50:  '#eef2ff',
          100: '#e0e7ff',
          500: '#6366f1',
          600: '#4f46e5',
          700: '#4338ca',
          900: '#312e81',
        },
        navy: {
          DEFAULT: '#0f1c3f',
          dark:    '#080e20',
        },
      },
      boxShadow: {
        subtle:   '0 1px 2px 0 rgb(0 0 0 / 0.04)',
        card:     '0 1px 3px 0 rgb(0 0 0 / 0.04), 0 4px 12px 0 rgb(0 0 0 / 0.06)',
        elevated: '0 4px 20px 0 rgb(0 0 0 / 0.10)',
        floating: '0 8px 40px 0 rgb(0 0 0 / 0.18)',
      },
      borderRadius: {
        card:   '16px',
        button: '12px',
        input:  '10px',
        sm:     '8px',
      },
      animation: {
        'fade-up':  'fadeUp 0.35s ease-out',
        'fade-in':  'fadeIn 0.25s ease-out',
        'slide-in': 'slideIn 0.3s ease-out',
      },
      keyframes: {
        fadeUp:  { '0%': { opacity:'0', transform:'translateY(8px)' }, '100%': { opacity:'1', transform:'none' } },
        fadeIn:  { '0%': { opacity:'0' },                              '100%': { opacity:'1' } },
        slideIn: { '0%': { opacity:'0', transform:'translateX(-8px)' },'100%': { opacity:'1', transform:'none' } },
      },
      typography: (theme) => ({
        DEFAULT: {
          css: {
            maxWidth: 'none',
            color: theme('colors.gray.700'),
            fontSize: '0.9rem',
            lineHeight: '1.75',
            a: {
              color: theme('colors.primary.600'),
              textDecoration: 'underline',
              textUnderlineOffset: '2px',
              '&:hover': { color: theme('colors.primary.700') },
            },
            strong: { color: theme('colors.gray.900'), fontWeight: '600' },
            h2: {
              fontSize: '1.25rem',
              fontWeight: '700',
              color: theme('colors.gray.900'),
              marginTop: '1.25rem',
              marginBottom: '0.5rem',
              paddingBottom: '0.35rem',
              borderBottom: `1px solid ${theme('colors.gray.200')}`,
            },
            h3: {
              fontSize: '1.1rem',
              fontWeight: '600',
              color: theme('colors.gray.800'),
              marginTop: '1rem',
              marginBottom: '0.4rem',
            },
            h4: {
              fontSize: '0.95rem',
              fontWeight: '600',
              color: theme('colors.gray.700'),
            },
            blockquote: {
              borderLeftColor: theme('colors.primary.500'),
              backgroundColor: '#f5f3ff',
              padding: '0.75rem 1rem',
              borderRadius: '0 8px 8px 0',
              fontStyle: 'italic',
              color: theme('colors.gray.600'),
            },
            code: {
              backgroundColor: theme('colors.gray.100'),
              color: '#dc2626',
              padding: '2px 6px',
              borderRadius: '4px',
              fontWeight: '500',
              fontSize: '0.85em',
              fontFamily: "'Fira Code', 'Courier New', monospace",
            },
            'code::before': { content: 'none' },
            'code::after': { content: 'none' },
            hr: { borderColor: theme('colors.gray.200') },
            thead: { borderBottomColor: theme('colors.gray.200') },
            'thead th': {
              fontWeight: '600',
              color: theme('colors.gray.700'),
              paddingLeft: '0.75rem',
              paddingRight: '0.75rem',
            },
            'tbody td': {
              paddingLeft: '0.75rem',
              paddingRight: '0.75rem',
            },
          },
        },
      }),
    },
  },
  plugins: [
    require('@tailwindcss/typography'),
  ],
}
```

- [ ] **Step 2: Verify the build still works**

```bash
cd frontend && npx next build 2>&1 | tail -5
```

Expected: Build completes without errors (warnings about pages are fine).

- [ ] **Step 3: Commit**

```bash
git add frontend/tailwind.config.js
git commit -m "config: add tailwind typography plugin with prose overrides"
```

---

### Task 3: Create the MarkdownRenderer component

**Files:**
- Create: `frontend/components/MarkdownRenderer.js`

- [ ] **Step 1: Create the component file**

Create `frontend/components/MarkdownRenderer.js` with the following content:

```jsx
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
```

- [ ] **Step 2: Verify import works**

```bash
cd frontend && node -e "require('./components/MarkdownRenderer')" 2>&1 || echo "Note: CJS require may fail for ESM — this is fine for Next.js"
```

This step is informational. The real test is in Task 6 (build verification).

- [ ] **Step 3: Commit**

```bash
git add frontend/components/MarkdownRenderer.js
git commit -m "feat: create shared MarkdownRenderer component with prose + syntax highlighting"
```

---

### Task 4: Remove old CSS and wire up chat pages

**Files:**
- Modify: `frontend/styles/globals.css` (remove lines 63-76)
- Modify: `frontend/pages/chat/[agentId].js` (remove MarkdownImage + MarkdownText, import MarkdownRenderer, fix bubble class)
- Modify: `frontend/pages/chat/team/[id].js` (remove inline ReactMarkdown, import MarkdownRenderer)
- Modify: `frontend/components/TeamContributions.js` (replace bare ReactMarkdown)

- [ ] **Step 1: Remove `.markdown-content` CSS from globals.css**

In `frontend/styles/globals.css`, delete lines 63-76 (the entire `/* ── Markdown inside chat bubbles ── */` section):

```css
/* DELETE THIS ENTIRE BLOCK: */
/* ── Markdown inside chat bubbles ──────── */
.markdown-content strong { font-weight: 700; }
.markdown-content em     { font-style: italic; }
.markdown-content code {
  font-family: 'Courier New', Courier, monospace;
  background-color: rgba(0,0,0,.06);
  padding: 2px 5px;
  border-radius: 4px;
  font-size: 0.875em;
}
.markdown-content ul { list-style: disc inside; margin: 6px 0; }
.markdown-content li { margin-left: 1rem; }
.markdown-content p  { margin-bottom: 4px; }
.markdown-content a  { color: #4f46e5; text-decoration: underline; }
```

- [ ] **Step 2: Update `pages/chat/[agentId].js`**

**2a. Replace the `ReactMarkdown` / `remarkGfm` imports (lines 36-37) with the MarkdownRenderer import:**

Remove:
```js
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
```

Add:
```js
import MarkdownRenderer from "../../components/MarkdownRenderer";
```

**2b. Delete the `MarkdownImage` component (lines 40-54) — it is now inside MarkdownRenderer.**

Delete from `const MarkdownImage = ({ src, alt, t }) => (` through the closing `);`.

**2c. Delete the `MarkdownText` component (lines 57-93) — replaced by MarkdownRenderer.**

Delete from `// Composant pour afficher du texte avec Markdown` through the closing `};` of `MarkdownText`.

**2d. Fix the agent message bubble className (around line 1057):**

Change:
```js
className={`rounded-card px-5 py-3.5 shadow-subtle max-w-[70%] whitespace-pre-line overflow-hidden transition-all duration-200 ${
```

To (remove `whitespace-pre-line`):
```js
className={`rounded-card px-5 py-3.5 shadow-subtle max-w-[70%] overflow-hidden transition-all duration-200 ${
```

**2e. Replace `<MarkdownText>` usage (around line 1100):**

Change:
```jsx
<MarkdownText>{msg.content}</MarkdownText>
```

To:
```jsx
<MarkdownRenderer>{msg.content}</MarkdownRenderer>
```

- [ ] **Step 3: Update `pages/chat/team/[id].js`**

**3a. Replace imports (lines 5-6):**

Remove:
```js
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
```

Add:
```js
import MarkdownRenderer from '../../../components/MarkdownRenderer';
```

**3b. Replace the inline ReactMarkdown block (lines 526-556).**

Replace this entire block:
```jsx
                    <div className="prose prose-sm max-w-none">
                      <ReactMarkdown
                        remarkPlugins={[remarkGfm]}
                        components={{
                          p: ({ node, ...props }) => <p className={msg.role === "user" ? "text-white mb-2 last:mb-0" : "text-gray-900 mb-2 last:mb-0"} {...props} />,
                          strong: ({ node, ...props }) => <strong className={msg.role === "user" ? "text-white font-bold" : "text-gray-900 font-bold"} {...props} />,
                          em: ({ node, ...props }) => <em className={msg.role === "user" ? "text-white italic" : "text-gray-700 italic"} {...props} />,
                          ul: ({ node, ...props }) => <ul className={`${msg.role === "user" ? "text-white" : "text-gray-900"} list-disc ml-4 mb-2`} {...props} />,
                          ol: ({ node, ...props }) => <ol className={`${msg.role === "user" ? "text-white" : "text-gray-900"} list-decimal ml-4 mb-2`} {...props} />,
                          li: ({ node, ...props }) => <li className="mb-1" {...props} />,
                          code: ({ node, inline, ...props }) =>
                            inline ? (
                              <code className={`${msg.role === "user" ? "bg-white/20 text-white" : "bg-gray-100 text-gray-900"} px-1.5 py-0.5 rounded text-sm`} {...props} />
                            ) : (
                              <code className={`block ${msg.role === "user" ? "bg-white/20 text-white" : "bg-gray-100 text-gray-900"} p-3 rounded-sm text-sm overflow-x-auto`} {...props} />
                            ),
                          a: ({ node, ...props }) => <a className={msg.role === "user" ? "text-blue-200 underline hover:text-blue-100" : "text-blue-600 underline hover:text-blue-800"} target="_blank" rel="noopener noreferrer" {...props} />,
                          table: ({ node, ...props }) => (
                            <div className="overflow-x-auto my-3">
                              <table className="min-w-full border-collapse border border-gray-200 rounded-sm text-sm" {...props} />
                            </div>
                          ),
                          thead: ({ node, ...props }) => <thead className="bg-gray-50" {...props} />,
                          th: ({ node, ...props }) => <th className="border border-gray-200 px-3 py-2 text-left font-semibold text-gray-700" {...props} />,
                          td: ({ node, ...props }) => <td className="border border-gray-200 px-3 py-2 text-gray-700" {...props} />,
                        }}
                      >
                        {msg.content}
                      </ReactMarkdown>
                      {msg.streaming && <span className="inline-block w-2 h-5 bg-primary-500 animate-pulse ml-0.5 align-text-bottom rounded-sm" />}
                    </div>
```

With:
```jsx
                    <div>
                      <MarkdownRenderer variant={msg.role === "user" ? "user" : "agent"}>
                        {msg.content}
                      </MarkdownRenderer>
                      {msg.streaming && <span className="inline-block w-2 h-5 bg-primary-500 animate-pulse ml-0.5 align-text-bottom rounded-sm" />}
                    </div>
```

- [ ] **Step 4: Update `components/TeamContributions.js`**

**4a. Replace imports (lines 4-5):**

Remove:
```js
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
```

Add:
```js
import MarkdownRenderer from './MarkdownRenderer';
```

**4b. Replace the ReactMarkdown usage (lines 98-104).**

Change:
```jsx
                  <div
                    className={`text-sm text-gray-700 prose prose-sm max-w-none ${
                      !isExpanded && isLong ? 'line-clamp-4' : ''
                    }`}
                  >
                    <ReactMarkdown remarkPlugins={[remarkGfm]}>
                      {content}
                    </ReactMarkdown>
                  </div>
```

To:
```jsx
                  <div
                    className={`text-sm text-gray-700 ${
                      !isExpanded && isLong ? 'line-clamp-4' : ''
                    }`}
                  >
                    <MarkdownRenderer variant="contribution">
                      {content}
                    </MarkdownRenderer>
                  </div>
```

- [ ] **Step 5: Commit**

```bash
git add frontend/styles/globals.css frontend/pages/chat/[agentId].js frontend/pages/chat/team/[id].js frontend/components/TeamContributions.js
git commit -m "refactor: wire up MarkdownRenderer across all chat pages, remove duplicated markdown config"
```

---

### Task 5: Build verification

- [ ] **Step 1: Run the build**

```bash
cd frontend && npx next build 2>&1 | tail -20
```

Expected: Build completes successfully. All pages compile without errors.

- [ ] **Step 2: Run lint**

```bash
cd frontend && npm run lint 2>&1
```

Expected: No new lint errors related to the changed files.

- [ ] **Step 3: Verify no leftover references to old components**

```bash
cd frontend && grep -rn "MarkdownText\|markdown-content" pages/ components/ styles/ --include="*.js" --include="*.css" 2>/dev/null
```

Expected: No results. All old references are gone.

---

### Task 6: Manual smoke test

No code changes — this is a verification task.

- [ ] **Step 1: Start dev server**

```bash
cd frontend && npm run dev
```

- [ ] **Step 2: Test agent chat**

Open an agent chat and send a prompt that generates rich markdown (e.g. "Donne-moi une analyse structurée avec des titres, une liste, un tableau et un bloc de code Python"). Verify:

- Headings (`h2`, `h3`) render with proper size hierarchy and `h2` has a bottom border
- Bullet lists (`ul`) and numbered lists (`ol`) render with proper indentation
- Tables render with zebra-striping, rounded container, horizontal scroll on narrow viewport
- Blockquotes render with purple left border and lavender background
- Code blocks render with dark background, syntax highlighting, language tag, and copy button
- Inline code renders with gray background and red monospace text
- `hr` renders as a subtle separator
- Streaming cursor still animates during response generation
- Sources and feedback buttons still work

- [ ] **Step 3: Test team chat**

Open a team chat and send a similar prompt. Verify:

- Agent messages render with the same quality as agent chat
- User messages render with white text, inverted colors for all elements
- TeamContributions accordion opens and markdown inside contribution cards renders correctly
- "Companions utilisés" button still works

- [ ] **Step 4: Test responsive**

Resize the browser to mobile width (~375px). Verify:

- Tables scroll horizontally within their container
- Code blocks scroll horizontally
- Message bubbles don't overflow the viewport
