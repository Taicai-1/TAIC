# Design: Unified MarkdownRenderer Component

**Date:** 2026-06-03
**Status:** Approved
**Scope:** Frontend chat message rendering (agent chat, team chat, team contributions)

## Problem

Markdown rendering in chat messages is duplicated across 3 files with inconsistencies:

1. `pages/chat/[agentId].js` — `MarkdownText` component (lines 57-93): missing `ol`, `h1`-`h6`, `blockquote`, `pre`, `hr`
2. `pages/chat/team/[id].js` — inline `ReactMarkdown` (lines 527-554): has inline/block code distinction but differs from agent chat
3. `components/TeamContributions.js` — bare `ReactMarkdown` with zero custom components (line 102-104), relies on `prose` class

Additional issues:
- `whitespace-pre-line` on agent message bubbles doubles line breaks with markdown
- No heading styles — `## Section` renders as plain text size
- No blockquote styles
- No code block rendering (only inline code in agent chat)
- No syntax highlighting
- Global `.markdown-content` CSS in `globals.css` (lines 63-76) partially conflicts with inline Tailwind classes

## Solution

### Architecture

One shared component `components/MarkdownRenderer.js` replaces all 3 implementations. It uses:
- `@tailwindcss/typography` (`prose` classes) for base typographic styling
- `react-syntax-highlighter` for code block syntax highlighting
- Custom component overrides via `ReactMarkdown`'s `components` prop for fine-tuned control

### Dependencies to Add

| Package | Purpose | Bundle impact |
|---------|---------|---------------|
| `@tailwindcss/typography` | Tailwind `prose` plugin for semantic HTML styling | ~3KB |
| `react-syntax-highlighter` | Syntax highlighting for code blocks | ~30KB (with light theme import) |

### Component: `components/MarkdownRenderer.js`

**Props:**
- `children: string` — markdown content to render
- `variant: "agent" | "user" | "contribution"` — controls color scheme
  - `"agent"` (default): dark text on white background
  - `"user"`: white text on gradient background (for user message bubbles)
  - `"contribution"`: compact sizing for TeamContributions cards

**Wrapper div:**
- Base classes: `prose prose-sm max-w-none` (from `@tailwindcss/typography`)
- Variant-specific color overrides via Tailwind `prose-invert` or custom classes

**Elements handled:**

| Element | Styling |
|---------|---------|
| `h1` | 1.5rem, bold, color #111827, margin top/bottom |
| `h2` | 1.25rem, bold, color #111827, border-bottom 1px solid #e5e7eb |
| `h3` | 1.1rem, semibold, color #1f2937 |
| `h4` | 0.95rem, semibold, color #374151 |
| `p` | margin-bottom 0.75rem, last:mb-0 |
| `strong` | font-weight 600, color #111827 |
| `em` | italic, color #4b5563 |
| `ul` | list-disc, padding-left 1.5rem |
| `ol` | list-decimal, padding-left 1.5rem |
| `li` | margin-bottom 0.25rem |
| `blockquote` | border-left 3px solid #6366f1, bg #f5f3ff, rounded-r-lg, italic |
| `a` | color #4f46e5, underline, target=_blank |
| `hr` | 1px solid #e5e7eb |
| `code` (inline) | bg #f3f4f6, color #dc2626, monospace, rounded, padding 2px 6px |
| `pre` + `code` | bg #1e293b, rounded-lg, syntax highlighted via `react-syntax-highlighter`, with language tag and copy button |
| `table` | wrapped in scrollable div with border, rounded corners |
| `thead` | bg #f9fafb |
| `th` | semibold, border-bottom 2px |
| `td` | border-bottom 1px, zebra-striped rows (even: bg #fafafa), hover highlight |
| `img` | reuses existing `MarkdownImage` component (max-height 512px, download/fullsize buttons) |

**User variant overrides:** When `variant="user"`, text colors become white, code backgrounds become `bg-white/20`, link colors become `text-blue-200`, blockquote background becomes semi-transparent white.

**Code block sub-component:**
- Extracts language from markdown fence (```python → "python")
- Renders with `react-syntax-highlighter` using `oneDark` or `atomOneDark` theme
- Shows language tag top-left
- Shows copy-to-clipboard button top-right
- Falls back to plain monospace if no language specified

### File Changes

#### New files
- `components/MarkdownRenderer.js` — the unified component

#### Modified files

**`pages/chat/[agentId].js`:**
- Remove `MarkdownImage` component (lines 40-54) — moved into `MarkdownRenderer`
- Remove `MarkdownText` component (lines 57-93) — replaced by `MarkdownRenderer`
- Import `MarkdownRenderer` from `components/MarkdownRenderer`
- Replace `<MarkdownText>{msg.content}</MarkdownText>` (line 1100) with `<MarkdownRenderer>{msg.content}</MarkdownRenderer>`
- Remove `whitespace-pre-line` from agent message bubble className (line 1057)

**`pages/chat/team/[id].js`:**
- Remove inline `ReactMarkdown` block (lines 527-554)
- Import `MarkdownRenderer` from `components/MarkdownRenderer`
- Replace with `<MarkdownRenderer variant={msg.role === "user" ? "user" : "agent"}>{msg.content}</MarkdownRenderer>`
- Remove `prose prose-sm max-w-none` from the wrapper div (line 526) — MarkdownRenderer handles this

**`components/TeamContributions.js`:**
- Remove `ReactMarkdown` and `remarkGfm` imports (lines 4-5)
- Import `MarkdownRenderer` from `./MarkdownRenderer`
- Replace `<ReactMarkdown remarkPlugins={[remarkGfm]}>{content}</ReactMarkdown>` (lines 102-104) with `<MarkdownRenderer variant="contribution">{content}</MarkdownRenderer>`
- Remove `prose prose-sm max-w-none` from wrapper div (line 98) — MarkdownRenderer handles this

**`styles/globals.css`:**
- Remove `.markdown-content` section (lines 63-76) — no longer needed

**`tailwind.config.js`:**
- Add `require('@tailwindcss/typography')` to plugins array
- Add `typography` overrides in `theme.extend` to match app color scheme (primary indigo, proper spacing)

**`package.json`:**
- Add `@tailwindcss/typography` and `react-syntax-highlighter` as dependencies

### What Does NOT Change

- Streaming cursor animation (pulse indicator)
- Sources panel, graph panel, feedback buttons — identical
- Chat bubble container styling (colors, padding, border-radius, shadows)
- Message data flow (API, state management)
- `MarkdownImage` functionality (just relocated into MarkdownRenderer)
- User message rendering when `variant="user"` preserves white-on-gradient style

### Testing

1. Agent chat: send a question that generates headings, lists, tables, code blocks, blockquotes
2. Team chat: same test, verify both user and agent messages render correctly
3. TeamContributions: expand contributions, verify markdown renders inside cards
4. Code blocks: verify syntax highlighting for Python, JavaScript, SQL at minimum
5. Copy button: click copy on a code block, verify clipboard content
6. Tables: verify horizontal scroll on narrow screens, zebra striping, hover
7. Responsive: test on mobile viewport — tables should scroll, code blocks should scroll
8. Streaming: verify cursor still animates correctly during response generation
