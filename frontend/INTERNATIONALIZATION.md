# Internationalization Guide

## Overview

TAIC Companion now supports French and English languages using `next-i18next` for Next.js.

## Implementation Status

### ✅ Phase 0: Configuration (Completed)
- Installed `next-i18next`, `react-i18next`, and `i18next`
- Configured Next.js i18n routing (`next.config.js`)
- Created `next-i18next.config.js` with translation namespaces
- Wrapped app with `appWithTranslation` HOC
- Created `LanguageSwitcher` component

### ✅ Phase 1: Authentication Pages (Partially Completed)
- **Completed:**
  - `pages/login.js` - Fully migrated with translations
  - Created `auth.json` translation files (FR/EN)

- **TODO:**
  - `pages/forgot-password.js` - Needs migration
  - `pages/reset-password.js` - Needs migration
  - `pages/agent-login.js` - Needs migration

### ✅ Phase 2: Common Translations (Completed)
- Created `common.json` - Buttons, navigation, labels, states, confirmations
- Created `errors.json` - Network, auth, validation, upload errors

### 🚧 Remaining Phases
- **Phase 3:** Profile and teams pages
- **Phase 4:** Complex pages (agents.js, index.js, chat pages)
- **Phase 5:** UI integration (add LanguageSwitcher to all pages)
- **Phase 6:** Backend error code standardization
- **Phase 7:** Testing and validation

## File Structure

```
frontend/
├── next.config.js              # i18n routing configuration
├── next-i18next.config.js      # Translation library config
├── components/
│   └── LanguageSwitcher.js     # Language selector component
└── public/
    └── locales/
        ├── en/                 # English translations
        │   ├── common.json
        │   ├── auth.json
        │   ├── agents.json
        │   ├── chat.json
        │   ├── teams.json
        │   ├── profile.json
        │   ├── dashboard.json
        │   └── errors.json
        └── fr/                 # French translations
            ├── common.json
            ├── auth.json
            ├── agents.json
            ├── chat.json
            ├── teams.json
            ├── profile.json
            ├── dashboard.json
            └── errors.json
```

## How to Use

### 1. In a Page Component

```javascript
import { useTranslation } from 'next-i18next'
import { serverSideTranslations } from 'next-i18next/serverSideTranslations'

export default function MyPage() {
  const { t } = useTranslation(['common', 'auth'])

  return (
    <div>
      <h1>{t('auth:login.title')}</h1>
      <button>{t('common:buttons.save')}</button>
    </div>
  )
}

// Required for SSR translations
export async function getStaticProps({ locale }) {
  return {
    props: {
      ...(await serverSideTranslations(locale, ['common', 'auth'])),
    },
  }
}
```

### 2. Translation Key Format

Use namespaced keys with the format: `namespace:category.subcategory.key`

Examples:
- `auth:login.title` → "Connexion" (FR) / "Login" (EN)
- `common:buttons.save` → "Enregistrer" (FR) / "Save" (EN)
- `errors:network.unreachable` → "Impossible de contacter le serveur" (FR)

### 3. Variables and Interpolation

```javascript
// In translation file:
{
  "documents": {
    "title": "Documents RAG ({{count}})"
  }
}

// In component:
t('agents:documents.title', { count: 5 })
// Result: "Documents RAG (5)"
```

### 4. Pluralization

```javascript
// In translation file (French):
{
  "document": "{{count}} document",
  "document_plural": "{{count}} documents"
}

// In component:
t('agents:document', { count: 0 })  // "0 document"
t('agents:document', { count: 1 })  // "1 document"
t('agents:document', { count: 5 })  // "5 documents"
```

### 5. Adding the Language Switcher

Import and add to your page header:

```javascript
import LanguageSwitcher from '../components/LanguageSwitcher'

// In your component JSX:
<header className="flex items-center justify-between">
  <h1>My Page</h1>
  <LanguageSwitcher />
</header>
```

## URL Structure

The i18n routing creates language-specific URLs:

- French (default): `/agents`, `/profile`, `/teams`
- English: `/en/agents`, `/en/profile`, `/en/teams`

Language preference is stored in a cookie (`NEXT_LOCALE`) for 1 year.

## Translation Namespaces

| Namespace | Purpose | Status |
|-----------|---------|--------|
| `common` | Shared buttons, labels, navigation | ✅ Complete |
| `errors` | Error messages (frontend + backend) | ✅ Complete |
| `auth` | Login, signup, password reset, agent login | ✅ Complete |
| `agents` | Companion management page | ✅ Complete |
| `chat` | Chat interface | 🚧 Placeholder |
| `teams` | Team management | 🚧 Placeholder |
| `profile` | User profile and GDPR | 🚧 Placeholder |
| `dashboard` | Main dashboard | 🚧 Placeholder |

## Best Practices

1. **Always use translation keys** - Never hardcode text strings
2. **Load required namespaces** - Only load what you need per page
3. **Use SSR translations** - Always add `getStaticProps` or `getServerSideProps`
4. **Consistent key naming** - Follow the established pattern
5. **Test both languages** - Verify layout doesn't break with longer text

## Adding New Translations

### Step 1: Add to Translation Files

Edit both `locales/fr/<namespace>.json` and `locales/en/<namespace>.json`:

```json
// locales/fr/mypage.json
{
  "title": "Mon titre",
  "button": "Cliquez ici"
}

// locales/en/mypage.json
{
  "title": "My title",
  "button": "Click here"
}
```

### Step 2: Update next-i18next.config.js

Add your namespace to the `ns` array if it's new:

```javascript
module.exports = {
  // ...
  ns: ['common', 'auth', 'agents', 'mypage'], // Add 'mypage'
  // ...
}
```

### Step 3: Use in Component

```javascript
const { t } = useTranslation(['mypage'])
// ...
<h1>{t('mypage:title')}</h1>
```

## Error Handling

For consistent error messages, use error codes from the backend:

```javascript
try {
  const response = await axios.post('/api/endpoint', data)
} catch (error) {
  const errorKey = error.response?.data?.error_code || 'network.unknown'
  toast.error(t(`errors:${errorKey}`))
}
```

## Testing

### Manual Testing Checklist

- [ ] Language switcher appears and functions correctly
- [ ] All text changes when switching languages
- [ ] No translation keys visible (e.g., `auth:login.title`)
- [ ] URLs update correctly (`/page` → `/en/page`)
- [ ] Language preference persists after refresh
- [ ] Date formatting uses correct locale
- [ ] Plurals work correctly (0, 1, 2+ items)
- [ ] Layout doesn't break with longer English text

### Build Test

```bash
cd frontend
npm run build
```

Verify:
- No translation errors in build output
- Bundle size is acceptable (i18n adds ~27KB)
- All pages build successfully

## Current Implementation Status

### Completed
✅ i18n configuration and setup
✅ Language switcher component
✅ Common translations (buttons, labels, navigation)
✅ Error message translations
✅ Auth translations (login page)
✅ Agents page translations (JSON files ready)

### Next Steps
1. Migrate remaining auth pages (forgot-password, reset-password, agent-login)
2. Complete detailed translations for:
   - Dashboard (index.js)
   - Chat pages
   - Teams pages
   - Profile page
3. Add LanguageSwitcher to all authenticated pages
4. Migrate agents.js to use translation keys
5. Full testing in both languages

## Notes

- **AI Responses:** Companion responses remain in the language of the user's question (not translated)
- **Date Formatting:** Use `i18n.language` for locale-aware date formatting
- **Backend Messages:** Error codes are mapped to translation keys in `errors.json`
- **Cookie:** Language preference stored as `NEXT_LOCALE` cookie (1 year expiration)
