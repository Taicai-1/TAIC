# Debug - Problème de connexion et langue

## 🔴 Problème rapporté

1. Sur `/en/login` (anglais), après connexion → reste sur page login ET repasse en français
2. Sur `/login` (français), après connexion → reste sur page login

## 🔍 Diagnostic

### Test 1: Vérifier la console du navigateur

1. Ouvrir http://localhost:3000/login
2. Ouvrir DevTools (F12) → onglet Console
3. Changer la langue en anglais
4. Entrer username/password
5. Cliquer "Log in"

**Regarder dans la console**:
- ✅ Doit afficher: `API_URL: http://localhost:8080`
- ✅ Doit afficher: `Making request to: http://localhost:8080/login`
- ✅ Doit afficher la réponse avec `access_token`

**Si erreur**:
- ❌ CORS error → Backend pas démarré ou CORS mal configuré
- ❌ 401 Unauthorized → Mauvais credentials
- ❌ Network error → Backend pas accessible
- ❌ 500 Internal Server Error → Erreur backend

### Test 2: Vérifier le localStorage

Après tentative de connexion:
1. DevTools → onglet Application
2. Storage → Local Storage → http://localhost:3000
3. Chercher la clé `token`

**Si token présent**: La connexion a réussi, le problème est la redirection
**Si token absent**: La connexion a échoué

### Test 3: Vérifier le router.locale

Ajouter temporairement dans login.js après ligne 37:

```javascript
console.log('Current locale:', router.locale);
console.log('Redirecting to:', `/agents`);
console.log('With locale:', router.locale);
```

Puis dans handleSubmit, ligne 61, changer:
```javascript
router.push("/agents", "/agents", { locale: router.locale });
```

En:
```javascript
console.log('About to redirect. Current locale:', router.locale);
router.push("/agents", "/agents", { locale: router.locale });
console.log('After router.push called');
```

### Test 4: Tester la redirection manuellement

Dans la console du navigateur, après login:
```javascript
// Vérifier le token
console.log('Token:', localStorage.getItem('token'));

// Tester la redirection
import { useRouter } from 'next/router';
window.location.href = '/en/agents'; // Force redirect
```

## 🛠️ Solutions possibles

### Solution 1: Vérifier que le backend fonctionne

```bash
# Terminal 1: Démarrer le backend
cd backend
python -m uvicorn main:app --reload --port 8080

# Terminal 2: Tester l'endpoint login
curl -X POST http://localhost:8080/login \
  -H "Content-Type: application/json" \
  -d '{"username": "test", "password": "test"}'
```

**Résultat attendu**: JSON avec `access_token`

### Solution 2: Forcer la redirection avec window.location

Si router.push ne fonctionne pas, utiliser une redirection "hard":

**Dans `frontend/pages/login.js`, ligne 60-61**:
```javascript
// OLD
toast.success(t('auth:login.success'));
router.push("/agents", "/agents", { locale: router.locale });

// NEW - Force hard redirect
toast.success(t('auth:login.success'));
const targetUrl = router.locale === 'en' ? '/en/agents' : '/agents';
window.location.href = targetUrl;
```

### Solution 3: Utiliser setTimeout pour laisser le toast s'afficher

```javascript
toast.success(t('auth:login.success'));
setTimeout(() => {
  router.push("/agents", "/agents", { locale: router.locale });
}, 500); // Attendre 500ms
```

### Solution 4: Vérifier les middlewares Next.js

Créer `frontend/middleware.js`:
```javascript
import { NextResponse } from 'next/server'

export function middleware(request) {
  console.log('Middleware - URL:', request.url);
  console.log('Middleware - Locale:', request.nextUrl.locale);
  return NextResponse.next();
}

export const config = {
  matcher: ['/((?!api|_next/static|_next/image|favicon.ico).*)'],
}
```

## 🧪 Test rapide

### Test A: Login fonctionne-t-il en français?

```
1. Aller sur http://localhost:3000/login
2. Langue: Français 🇫🇷
3. Username: test
4. Password: test
5. Cliquer "Se connecter"
```

**Résultat attendu**: Redirection vers `/agents`
**Si ça ne marche pas**: Problème de backend ou de credentials

### Test B: Login fonctionne-t-il en anglais?

```
1. Aller sur http://localhost:3000/en/login
2. Langue: English 🇬🇧
3. Username: test
4. Password: test
5. Cliquer "Log in"
```

**Résultat attendu**: Redirection vers `/en/agents`
**Si redirection vers `/agents`**: Problème de locale dans router.push

### Test C: Le changement de langue fonctionne-t-il?

```
1. Aller sur http://localhost:3000/login
2. Cliquer sur 🇬🇧 English
```

**Vérifications**:
- ✅ URL devient `/en/login`
- ✅ Texte change en anglais
- ✅ Cookie `NEXT_LOCALE=en` créé (DevTools → Application → Cookies)

## 📋 Checklist de debug

- [ ] Backend est démarré (`http://localhost:8080`)
- [ ] Endpoint `/login` fonctionne (test avec curl)
- [ ] Credentials corrects (username/password existent en DB)
- [ ] Token est stocké dans localStorage après login
- [ ] Console montre `router.locale` correct
- [ ] Pas d'erreur dans console navigateur
- [ ] Pas d'erreur dans terminal backend
- [ ] Cookie `NEXT_LOCALE` est créé
- [ ] router.push est appelé avec la bonne locale

## 🔧 Fix temporaire immédiat

Si tout échoue, utiliser cette version dans `login.js`:

```javascript
if (isLogin) {
  localStorage.setItem("token", response.data.access_token);
  toast.success(t('auth:login.success'));

  // Hard redirect avec locale
  const locale = router.locale || 'fr';
  window.location.href = locale === 'en' ? '/en/agents' : '/agents';
} else {
  toast.success(t('auth:signup.success'));
  setIsLogin(true);
}
```

## 📞 Si problème persiste

Vérifier:
1. Logs backend
2. Network tab dans DevTools (voir la requête POST /login)
3. Response de la requête (contient-elle `access_token`?)
4. Console errors
5. Version de Next.js: `npm list next`

---

**Prochaine étape**: Faire Test A, Test B, Test C et rapporter les résultats
