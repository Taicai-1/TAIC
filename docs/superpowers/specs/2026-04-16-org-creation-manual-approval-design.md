# Design — Validation manuelle de la création d'organisation

**Date :** 2026-04-16
**Statut :** Approuvé, en attente d'implémentation
**Phase projet :** Beta fermée (early access)

---

## 1. Contexte et problème

Aujourd'hui, n'importe quel utilisateur authentifié peut appeler `POST /api/companies` (`backend/main.py:4714`) et créer une organisation, ce qui le fait automatiquement `owner` et débloque toutes les fonctionnalités du produit (agents, teams, intégrations Neo4j/Notion/Slack, partage d'agents, etc.).

Pendant la phase beta fermée de TAIC, il faut garder le contrôle sur qui obtient une organisation. La création de compte utilisateur reste libre (risque faible, classique SaaS), mais la création d'organisation doit passer par une **approbation manuelle de Jeremy (jeremy@taic.co)**.

## 2. Objectifs

- Empêcher la création automatique d'organisation par les utilisateurs standards
- Notifier l'administrateur à chaque demande avec un lien de validation "1 clic"
- Permettre l'approbation ou le refus de chaque demande
- Informer le demandeur du résultat par email
- Rester simple : pas d'admin panel, pas de gestion de rôles côté application
- Laisser la porte ouverte à une évolution future vers du self-serve automatique

## 3. Non-objectifs

- Pas d'admin panel dans l'app Next.js (remis à plus tard)
- Pas de billing / gating par paiement
- Pas de vérification d'email côté utilisateur avant soumission
- Pas de TTL strict sur les demandes en attente (gestion manuelle)

## 4. Architecture générale

Flux en 4 étapes :

1. Utilisateur connecté clique "Créer une organisation" → saisit le nom → `POST /api/companies/request`
2. Backend crée une ligne dans `company_creation_requests` (status=`pending`) + envoie un email HTML à `jeremy@taic.co` avec 2 liens signés (Approuver / Refuser)
3. Jeremy clique sur un lien → page de confirmation backend → POST de décision → crée (ou pas) la `Company` + `CompanyMembership` + update le status de la request
4. Le demandeur reçoit un email ("✅ Approuvée" ou "❌ Refusée") et au prochain refresh voit soit son dashboard complet, soit un message

**Principe clé :** séparation entre "request" (la demande) et "company" (la ressource finale) pour historique, audit, et future extension (passage en self-serve = changer la logique d'approbation automatique).

## 5. Modèle de données

### Nouvelle table `company_creation_requests`

| Colonne | Type | Notes |
|---|---|---|
| `id` | Integer PK | |
| `user_id` | FK users.id, `ON DELETE CASCADE` | demandeur |
| `requested_name` | String(200) | nom souhaité pour l'org |
| `status` | String(20) | `pending` \| `approved` \| `rejected` |
| `token` | String(128) unique | utilisé dans les magic links admin |
| `created_at` | DateTime, default=now | |
| `decided_at` | DateTime nullable | quand admin a cliqué |
| `decided_reason` | Text nullable | optionnel, raison de refus |
| `company_id` | FK companies.id nullable | rempli si approuvé |

### Contraintes

- Index sur `user_id` et `token`
- `FOREIGN KEY (user_id) ON DELETE CASCADE` pour éviter les requests orphelines
- Contrainte applicative : un user ne peut avoir qu'une seule request `pending` à la fois
- Le token est généré par `secrets.token_urlsafe(48)` (imprévisible, 64 chars, usage unique validé par `status == 'pending'`)

### Migration

Nouveau fichier SQL dans `backend/migrations/` (additive, pas de breaking change sur les tables existantes).

## 6. Endpoints backend

### Nouveaux endpoints

#### `POST /api/companies/request` (auth requis)

- Body : `{ "name": "Ma Boîte" }`
- Vérifications :
  - user pas déjà membre d'une org (via `CompanyMembership`)
  - pas de request `pending` existante pour ce user
  - nom non-vide, min 2 / max 200 caractères, sanitizé
- Crée la ligne `company_creation_requests` + envoie l'email admin
- Retourne : `{ "status": "pending", "requested_name": "..." }`

#### `GET /api/companies/request/mine` (auth requis)

- Retourne la dernière request du user (ou `null`)
- Utilisé par le frontend pour afficher l'écran "en attente" ou "refusée"

#### `GET /api/admin/companies/request/{token}?action=approve|reject`

- Pas d'auth classique : le token EST l'auth
- Retourne une page HTML simple (rendue par le backend) demandant confirmation avec un bouton "Confirmer"
- **Motivation** : Gmail pré-fetch les URLs dans les emails. Si l'action était exécutée au GET, l'org serait approuvée sans clic humain.

#### `POST /api/admin/companies/request/{token}/decide`

- Appelé par le bouton de confirmation
- Body : `{ "action": "approve" | "reject", "reason": "optional" }`
- Vérifie token valide + `status == 'pending'` (anti double-clic / replay)
- Si `approve` :
  - Vérifie que `requested_name` n'est pas pris (unique constraint sur `Company.name`)
  - Crée la `Company` (avec `invite_code` généré) + `CompanyMembership` owner
  - Update la request (`status=approved`, `decided_at`, `company_id`)
  - Envoie email user "approuvée"
- Si `reject` :
  - Update la request (`status=rejected`, `decided_at`, `decided_reason`)
  - Envoie email user "refusée"
- Retourne : page HTML de confirmation ("✅ Organisation approuvée" ou "❌ Demande refusée")

### Endpoints remplacés

- `POST /api/companies` : désactivé (retour 403 "La création d'organisation doit passer par le flux de demande") ou supprimé après bascule frontend complète

### Rate limiting

- Le check "1 request pending max par user" limite naturellement l'abus
- Pas de rate limit IP supplémentaire pour la V1 (à ajouter si spam observé)

## 7. Frontend

### Page d'accueil / dashboard (`pages/index.js`)

Au mount, si `useAuth()` retourne un user sans `company_id` :

- Appel à `api.get('/api/companies/request/mine')`
- 3 états possibles :
  - **Pas de request** → formulaire "Créer votre organisation" (1 champ `name`) + bouton "Demander"
  - **Request `pending`** → écran "⏳ Votre demande pour *'Ma Boîte'* est en cours d'examen. Vous recevrez un email dès qu'elle sera traitée."
  - **Request `rejected`** → "❌ Votre précédente demande a été refusée" + raison si fournie + bouton "Soumettre une nouvelle demande"

### Formulaire de demande

- Validation côté client (nom min 2 / max 200 caractères)
- `api.post('/api/companies/request', { name })`
- Toast de confirmation + switch vers l'état `pending`

### Gating des pages authentifiées

- Les pages qui requièrent une org (agents, teams, etc.) doivent rediriger vers l'accueil si `user.company_id` est null
- À implémenter : audit des pages et centralisation du gate dans `useAuth()` ou `Layout.js` via un flag `hasOrg`

### Pas de pages admin dans Next.js

- Les liens admin dans l'email pointent vers le backend directement
- Pages HTML simples rendues par le backend (string template), brandées cohéremment

## 8. Emails

Tous via `email_service.py` (`send_email` + `_wrap_template` déjà existants).

### Email admin "Nouvelle demande"

- Destinataire : `ADMIN_NOTIFICATION_EMAIL` (env var, default `jeremy@taic.co`)
- Objet : `🏢 Nouvelle demande : "Ma Boîte" par user@example.com`
- Corps : email demandeur, nom souhaité, date, 2 boutons (Approuver vert / Refuser rouge)
- Les boutons pointent vers `GET /api/admin/companies/request/{token}?action=approve` (page de confirmation)

### Email user "Organisation approuvée"

- Objet : `✅ Votre organisation "Ma Boîte" a été approuvée`
- Corps : confirmation + CTA "Accéder à mon espace"

### Email user "Demande refusée"

- Objet : `Votre demande d'organisation`
- Corps : message neutre, raison si fournie, CTA "Soumettre une nouvelle demande"

## 9. Sécurité & edge cases

### Pré-fetch Gmail

- Gmail scanne les liens dans les emails → les liens ne déclenchent **jamais** l'action au GET
- Solution : page de confirmation intermédiaire avec bouton POST

### Double-clic / race conditions

- Transaction DB + check `status == 'pending'` avant d'agir
- Le second clic reçoit "cette demande a déjà été traitée"

### Collision de noms

- Contrainte `UNIQUE` sur `Company.name` déjà en place
- Vérification au moment de l'approbation (pas à la demande) : si le nom est pris entre-temps, l'admin voit une erreur et peut refuser

### Abus côté user

- "1 pending max par user" (check applicatif)
- "user pas déjà membre d'une org" (check applicatif)
- Rate limit IP : non V1, à ajouter si besoin

### Fuite du token admin

- Si l'email est intercepté, quelqu'un peut approuver
- Risque accepté pour la beta : seul `jeremy@taic.co` reçoit l'email, Google Workspace 2FA protège la boîte
- Amélioration future possible : exiger que l'admin soit connecté à l'app au moment du clic

### Suppression utilisateur

- `ON DELETE CASCADE` sur `user_id` → la request est supprimée automatiquement si le user est supprimé

### TTL des requests

- Pas de TTL pour la V1
- Les requests `pending` restent indéfiniment (gestion manuelle)
- Tâche de cleanup ajoutable plus tard si besoin

## 10. Tests

### Tests unitaires backend (pytest, pas de DB)

- Validation du nom d'org dans `POST /api/companies/request` (min/max length, sanitization, vides)
- Génération de token : unicité, longueur, imprévisibilité (smoke test)
- Email template rendering : les 3 templates produisent du HTML non vide avec les placeholders substitués

### Tests d'intégration (optionnels V1)

- Flux complet approve : request → email mocké → approve → company créée + membership owner
- Flux complet reject : request → reject → pas de company créée
- Anti-replay : approve 2x → 2e rejeté

### Pas de tests

- Pas d'envoi d'email réel (mock SMTP)
- Pas de tests frontend (pas d'infra existante)

### Cible V1

- ~5-8 tests unitaires, objectif anti-régression basique, pas de course à la couverture

## 11. Plan de déploiement

### Ordre des changements

1. Migration SQL : nouvelle table `company_creation_requests`
2. Backend : nouveaux endpoints + templates email (l'ancien `POST /api/companies` reste actif en parallèle)
3. Frontend : ajout du composant de demande + appel au nouvel endpoint
4. Bascule : l'UI appelle désormais `/api/companies/request`
5. Cleanup : désactivation (403) ou suppression de l'ancien `POST /api/companies`

### Données existantes

- Pas de rétro-migration : les companies créées avant le changement restent telles quelles
- Les users déjà membres d'une org ne passent pas par le nouveau flux

### Variables d'environnement

Nouvelles :
- `ADMIN_NOTIFICATION_EMAIL=jeremy@taic.co` (Cloud Run backend + `.env.example`)
- URL publique du backend pour construire les liens admin (à vérifier si `BACKEND_PUBLIC_URL` existe déjà ou doit être ajoutée)

### Rollback

- Possible tant que l'ancien `POST /api/companies` n'est pas supprimé
- La table `company_creation_requests` peut rester en base (pas de data loss)

### CI

- Les nouveaux tests tournent dans la pipeline existante (pytest)
- Ruff et ESLint couvrent les nouveaux fichiers

## 12. Évolutions futures (hors scope)

- Admin panel Next.js pour gérer les requests
- Self-serve automatique avec rate limit + vérification d'email + billing
- Décomposition role-based : "superadmin" TAIC pour gérer les requests sans passer par email
- TTL automatique des requests pending (ex. 30 jours)
- Dashboard analytics des demandes (taux d'approbation, temps moyen de décision, etc.)
