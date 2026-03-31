# Test de diagnostic - Problème de connexion et langue

## ✅ Modifications appliquées

J'ai ajouté des logs de debug encore plus détaillés dans `frontend/pages/login.js`:

- 🍪 Vérification que le cookie NEXT_LOCALE est bien défini
- 📍 Vérification de la locale détectée
- 🔍 Double vérification avant la redirection
- ⏱️ Timeout augmenté à 1000ms (au lieu de 500ms)

## 🧪 Test à effectuer

### Étape 1: Démarrer le frontend

```bash
cd frontend
npm run dev
```

### Étape 2: Ouvrir le navigateur avec DevTools

1. Ouvrir Chrome/Edge
2. Appuyer sur **F12** pour ouvrir DevTools
3. Aller dans l'onglet **Console**
4. Garder DevTools ouvert pendant toute la procédure

### Étape 3: Tester la connexion en anglais

1. Aller sur: `http://localhost:3000/login`
2. Cliquer sur le sélecteur de langue (🇬🇧 English)
3. **VÉRIFIER**: L'URL doit devenir `/en/login`
4. Entrer vos identifiants:
   - Username: `test` (ou votre username)
   - Password: `test` (ou votre password)
5. Cliquer sur "Log in"
6. **OBSERVER** la console DevTools

### Étape 4: Analyser les logs console

Vous devriez voir une séquence de logs avec émojis:

```
API_URL: http://localhost:8080
Making request to: http://localhost:8080/login
Payload: {username: "test", password: "test"}
✅ Login response received: {access_token: "..."}
🔑 Storing token...
🌍 Current locale: en
📍 Detected locale: en
🍪 Cookie set: NEXT_LOCALE=en; ...
🎯 Target path: /en/agents
⏳ Redirecting in 1000ms...
🚀 Executing redirect to: /en/agents
🔍 Final check - router.locale: en
🔍 Final check - cookies: NEXT_LOCALE=en; ...
```

### Étape 5: Identifier le problème

**CAS A: Pas de logs du tout**
- ❌ Le backend n'est pas démarré ou inaccessible
- **Solution**: Démarrer le backend sur port 8080

**CAS B: Logs s'arrêtent à "Making request to..."**
- ❌ Erreur CORS ou backend qui ne répond pas
- **Solution**: Vérifier que le backend tourne et accepte les requêtes

**CAS C: Erreur 401 Unauthorized**
- ❌ Mauvais identifiants
- **Solution**: Vérifier username/password en base de données

**CAS D: Tous les logs apparaissent mais pas de redirection**
- ❌ Problème JavaScript ou window.location.href bloqué
- **Regarder**: Onglet "Network" pour voir si une requête vers /en/agents est faite

**CAS E: Redirection vers /agents au lieu de /en/agents**
- ❌ `router.locale` n'est pas 'en' mais 'fr'
- **Regarder**: Le log `🌍 Current locale: ...` et `📍 Detected locale: ...`
- **Problème**: La locale n'est pas détectée correctement

**CAS F: Logs OK mais retour immédiat à /login**
- ❌ La page /agents redirige vers /login car le token n'est pas trouvé
- **Cause possible**: Race condition entre localStorage.setItem et le chargement de /agents

### Étape 6: Vérifier le localStorage

Après la tentative de connexion:

1. DevTools → Onglet **Application**
2. Storage → **Local Storage** → `http://localhost:3000`
3. Chercher la clé `token`

**Si le token est présent**: La connexion a réussi, le problème est la redirection
**Si le token est absent**: La connexion a échoué

### Étape 7: Vérifier les cookies

1. DevTools → Onglet **Application**
2. Storage → **Cookies** → `http://localhost:3000`
3. Chercher `NEXT_LOCALE`

**Valeur attendue**: `en` (si vous avez changé en anglais)
**Si la valeur est `fr`**: La locale n'est pas préservée

## 📊 Résultats à me communiquer

Merci de me fournir:

1. **Les logs de la console** (copier-coller tout ce qui apparaît avec les émojis)
2. **L'URL finale** après la tentative de connexion
3. **Valeur du token** dans localStorage (juste confirmer présent/absent, pas la valeur complète)
4. **Valeur de NEXT_LOCALE** dans les cookies
5. **Capture d'écran** de la console si possible

## 🔧 Si le backend n'est pas démarré

```bash
# Terminal séparé
cd backend
python -m uvicorn main:app --reload --port 8080
```

Vous devriez voir:
```
INFO:     Uvicorn running on http://127.0.0.1:8080 (Press CTRL+C to quit)
```

## 🎯 Test alternatif: Connexion en français

Si le test en anglais échoue, essayez en français:

1. Aller sur: `http://localhost:3000/login`
2. **NE PAS** changer la langue (rester en français)
3. Se connecter
4. Observer si la redirection vers `/agents` fonctionne

Si ça marche en français mais pas en anglais → Problème spécifique à la gestion de la locale anglaise

---

**Prochaine étape**: Effectuer ce test et me communiquer les résultats des logs console
