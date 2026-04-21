# Slash Commands Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add configurable slash-command prompt shortcuts to companions, managed at the organization level.

**Architecture:** JSON field `slash_commands` on the `Team` model (reusing the Company entity as "organization"). CRUD via 2 new endpoints. Frontend parses `/command` in chat input, resolves to prompt, sends prompt to `/ask`. Autocomplete menu in chat.

**Tech Stack:** FastAPI, SQLAlchemy (Text/JSON column), Next.js, React, Tailwind CSS, Lucide icons

---

## File Structure

| File | Action | Responsibility |
|------|--------|---------------|
| `backend/database.py` | Modify | Add `slash_commands` column to `Company` model |
| `backend/main.py` | Modify | Add GET/PUT slash-commands endpoints, modify DELETE agent cleanup |
| `frontend/pages/organization.js` | Modify | Add "Raccourcis Prompts" settings section with table + modal |
| `frontend/pages/chat/[agentId].js` | Modify | Add autocomplete menu + command resolution in sendMessage |

**Note:** After exploring the codebase, the organization entity is `Company` (not `Team`). The settings page uses `/api/companies/*` endpoints. We store `slash_commands` on the `Company` model since this is an org-level feature.

---

### Task 1: Add `slash_commands` column to Company model

**Files:**
- Modify: `backend/database.py` (Company model, around line 370)

- [ ] **Step 1: Add the column to the Company model**

In `backend/database.py`, find the `Company` class and add the new column after the existing fields:

```python
slash_commands = Column(Text, nullable=True)  # JSON: [{"id":"uuid","command":"name","prompt":"text","agent_ids":[1,2]}]
```

- [ ] **Step 2: Verify the backend starts without errors**

Run: `cd backend && python -c "from database import Company; print([c.name for c in Company.__table__.columns])"`
Expected: list includes `'slash_commands'`

- [ ] **Step 3: Commit**

```bash
git add backend/database.py
git commit -m "feat: add slash_commands column to Company model"
```

---

### Task 2: Add GET/PUT slash-commands API endpoints

**Files:**
- Modify: `backend/main.py` (near the `/api/companies/*` endpoints, around line 5092+)

- [ ] **Step 1: Add Pydantic model for slash command validation**

At the top of `main.py` near other Pydantic models, add:

```python
import re as _re

class SlashCommandItem(BaseModel):
    id: Optional[str] = None
    command: str
    prompt: str
    agent_ids: list[int] = []

    @validator("command")
    def validate_command(cls, v):
        if not _re.match(r'^[a-zA-Z0-9_-]+$', v) or len(v) > 32:
            raise ValueError("Command must be alphanumeric/hyphens/underscores, max 32 chars")
        return v.lower()

    @validator("prompt")
    def validate_prompt(cls, v):
        if not v.strip() or len(v) > 5000:
            raise ValueError("Prompt must be non-empty and max 5000 chars")
        return v
```

- [ ] **Step 2: Add GET endpoint**

After the existing `/api/companies/*` endpoints in `main.py`:

```python
@app.get("/api/companies/slash-commands")
async def get_slash_commands(
    agent_id: Optional[int] = None,
    user_id: str = Depends(verify_token),
    db: Session = Depends(get_db),
):
    """Get slash commands for the caller's company. Optional agent_id filter."""
    company_id = _get_caller_company_id(user_id, db)
    if not company_id:
        raise HTTPException(status_code=404, detail="No company found")
    company = db.query(Company).filter(Company.id == company_id).first()
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")

    commands = json.loads(company.slash_commands) if company.slash_commands else []
    if agent_id is not None:
        commands = [c for c in commands if agent_id in c.get("agent_ids", [])]
    return {"slash_commands": commands}
```

- [ ] **Step 3: Add PUT endpoint**

```python
@app.put("/api/companies/slash-commands")
async def update_slash_commands(
    request: Request,
    user_id: str = Depends(verify_token),
    db: Session = Depends(get_db),
):
    """Replace all slash commands for the caller's company. Owner/admin only."""
    company_id = _get_caller_company_id(user_id, db)
    if not company_id:
        raise HTTPException(status_code=404, detail="No company found")

    # Check role
    user = get_cached_user(int(user_id), db)
    membership = db.query(CompanyMember).filter(
        CompanyMember.company_id == company_id,
        CompanyMember.user_id == int(user_id)
    ).first()
    if not membership or membership.role not in ("owner", "admin"):
        raise HTTPException(status_code=403, detail="Owner or admin required")

    body = await request.json()
    items = body if isinstance(body, list) else body.get("slash_commands", [])

    # Validate each item
    seen_commands = set()
    validated = []
    for item in items:
        sc = SlashCommandItem(**item)
        if sc.command in seen_commands:
            raise HTTPException(status_code=400, detail=f"Duplicate command: {sc.command}")
        seen_commands.add(sc.command)

        # Validate agent_ids exist and belong to company
        for aid in sc.agent_ids:
            agent = db.query(Agent).filter(Agent.id == aid).first()
            if not agent:
                raise HTTPException(status_code=400, detail=f"Agent {aid} not found")

        validated.append({
            "id": sc.id or str(uuid.uuid4()),
            "command": sc.command,
            "prompt": sc.prompt,
            "agent_ids": sc.agent_ids,
        })

    company = db.query(Company).filter(Company.id == company_id).first()
    company.slash_commands = json.dumps(validated)
    db.commit()

    return {"slash_commands": validated}
```

- [ ] **Step 4: Verify endpoints respond**

Run: `cd backend && python -c "from main import app; print('Endpoints loaded OK')"`
Expected: no import errors

- [ ] **Step 5: Commit**

```bash
git add backend/main.py
git commit -m "feat: add GET/PUT /api/companies/slash-commands endpoints"
```

---

### Task 3: Add agent cleanup on DELETE

**Files:**
- Modify: `backend/main.py` (DELETE `/agents/{agent_id}` endpoint, line 2507-2525)

- [ ] **Step 1: Add cleanup logic after agent deletion**

In the `delete_agent` function at line 2507, after `_delete_agent_and_related_data(agent, int(user_id), db)` (line 2516) and before `db.commit()` (line 2517), add:

```python
        # Clean up slash_commands references in the agent's company
        if agent.company_id:
            company = db.query(Company).filter(Company.id == agent.company_id).first()
            if company and company.slash_commands:
                try:
                    commands = json.loads(company.slash_commands)
                    updated = False
                    for cmd in commands:
                        if agent_id in cmd.get("agent_ids", []):
                            cmd["agent_ids"] = [aid for aid in cmd["agent_ids"] if aid != agent_id]
                            updated = True
                    if updated:
                        company.slash_commands = json.dumps(commands)
                except (json.JSONDecodeError, TypeError):
                    pass
```

Note: Check if `Agent` model has `company_id` field. If not, resolve via the user's company: `user_company_id = _get_caller_company_id(user_id, db)` and use that instead.

- [ ] **Step 2: Commit**

```bash
git add backend/main.py
git commit -m "feat: clean up slash_commands when agent is deleted"
```

---

### Task 4: Add Slash Commands settings section to organization page

**Files:**
- Modify: `frontend/pages/organization.js`

- [ ] **Step 1: Add state variables**

After the existing state declarations (around line 80, after `shareLoading`), add:

```javascript
  // Slash commands
  const [slashCommands, setSlashCommands] = useState([]);
  const [slashModalOpen, setSlashModalOpen] = useState(false);
  const [slashEditItem, setSlashEditItem] = useState(null); // null = new, object = editing
  const [slashForm, setSlashForm] = useState({ command: '', prompt: '', agent_ids: [] });
  const [slashLoading, setSlashLoading] = useState(false);
  const [slashOpen, setSlashOpen] = useState(false);
```

- [ ] **Step 2: Add load function and wire into loadCompany**

After `loadOrgAgents` function (around line 140), add:

```javascript
  const loadSlashCommands = async () => {
    try {
      const res = await api.get('/api/companies/slash-commands');
      setSlashCommands(res.data.slash_commands || []);
    } catch {}
  };
```

In `loadCompany` (line 106-110), add `loadSlashCommands()` alongside `loadOrgAgents()`:

```javascript
      if (data.company && ['admin', 'owner'].includes(data.company.role)) {
        loadMembers();
        loadOrgAgents();
        loadSlashCommands();
        if (data.company.role === 'owner') loadIntegrations();
      }
```

- [ ] **Step 3: Add save/delete handler functions**

After `loadSlashCommands`:

```javascript
  const handleSaveSlashCommand = async () => {
    if (!slashForm.command.trim() || !slashForm.prompt.trim()) {
      toast.error(t('organization:slashCommands.errors.requiredFields'));
      return;
    }
    setSlashLoading(true);
    try {
      let updated;
      if (slashEditItem) {
        updated = slashCommands.map(c =>
          c.id === slashEditItem.id
            ? { ...c, command: slashForm.command.toLowerCase(), prompt: slashForm.prompt, agent_ids: slashForm.agent_ids }
            : c
        );
      } else {
        updated = [...slashCommands, {
          command: slashForm.command.toLowerCase(),
          prompt: slashForm.prompt,
          agent_ids: slashForm.agent_ids,
        }];
      }
      const res = await api.put('/api/companies/slash-commands', { slash_commands: updated });
      setSlashCommands(res.data.slash_commands || []);
      setSlashModalOpen(false);
      setSlashEditItem(null);
      setSlashForm({ command: '', prompt: '', agent_ids: [] });
      toast.success(slashEditItem ? t('organization:slashCommands.updated') : t('organization:slashCommands.created'));
    } catch (error) {
      toast.error(error.response?.data?.detail || t('organization:errors.generic'));
    } finally {
      setSlashLoading(false);
    }
  };

  const handleDeleteSlashCommand = (id) => {
    if (!confirm(t('organization:slashCommands.deleteConfirm'))) return;
    const updated = slashCommands.filter(c => c.id !== id);
    api.put('/api/companies/slash-commands', { slash_commands: updated })
      .then(res => {
        setSlashCommands(res.data.slash_commands || []);
        toast.success(t('organization:slashCommands.deleted'));
      })
      .catch(error => toast.error(error.response?.data?.detail || t('organization:errors.generic')));
  };

  const openSlashEdit = (item) => {
    setSlashEditItem(item);
    setSlashForm({ command: item.command, prompt: item.prompt, agent_ids: item.agent_ids || [] });
    setSlashModalOpen(true);
  };

  const openSlashCreate = () => {
    setSlashEditItem(null);
    setSlashForm({ command: '', prompt: '', agent_ids: [] });
    setSlashModalOpen(true);
  };
```

- [ ] **Step 4: Add the Lucide icons import**

At the top of the file, add `Zap, Edit3` to the lucide-react import (Zap for the section icon, Edit3 for edit button):

```javascript
import {
  // ... existing imports ...
  Zap,
  Edit3,
} from 'lucide-react';
```

- [ ] **Step 5: Add the JSX section**

After the Integrations section closing `)}` (around line 750) and before the Org Agents section (line 752), add:

```jsx
              {/* ---- Slash Commands (admin/owner) ---- */}
              {['admin', 'owner'].includes(company.role) && (
                <div className="bg-white rounded-card shadow-card border border-gray-200 p-8">
                  <button onClick={() => setSlashOpen(!slashOpen)} className="w-full flex items-center justify-between mb-4">
                    <div className="flex items-center space-x-3">
                      <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-purple-400 to-purple-600 flex items-center justify-center">
                        <Zap className="w-5 h-5 text-white" />
                      </div>
                      <div className="text-left">
                        <h2 className="text-xl font-heading font-bold text-gray-900">{t('organization:slashCommands.title')}</h2>
                        <p className="text-gray-500 text-sm">{t('organization:slashCommands.description')}</p>
                      </div>
                    </div>
                    {slashOpen ? <ChevronUp className="w-5 h-5 text-gray-400" /> : <ChevronDown className="w-5 h-5 text-gray-400" />}
                  </button>

                  {slashOpen && (
                    <div>
                      <div className="flex justify-end mb-4">
                        <button onClick={openSlashCreate}
                          className="px-4 py-2 bg-gradient-to-r from-purple-500 to-purple-600 hover:from-purple-600 hover:to-purple-700 text-white text-sm font-semibold rounded-button shadow-card transition-all">
                          + {t('organization:slashCommands.addButton')}
                        </button>
                      </div>

                      {slashCommands.length === 0 ? (
                        <p className="text-gray-400 text-sm text-center py-8">{t('organization:slashCommands.empty')}</p>
                      ) : (
                        <div className="overflow-x-auto">
                          <table className="w-full text-sm">
                            <thead>
                              <tr className="border-b border-gray-200 text-left">
                                <th className="pb-3 font-medium text-gray-500">{t('organization:slashCommands.table.command')}</th>
                                <th className="pb-3 font-medium text-gray-500">{t('organization:slashCommands.table.prompt')}</th>
                                <th className="pb-3 font-medium text-gray-500">{t('organization:slashCommands.table.companions')}</th>
                                <th className="pb-3 font-medium text-gray-500 w-24"></th>
                              </tr>
                            </thead>
                            <tbody>
                              {slashCommands.map(cmd => (
                                <tr key={cmd.id} className="border-b border-gray-100">
                                  <td className="py-3 pr-4">
                                    <code className="bg-purple-50 text-purple-700 px-2 py-1 rounded text-xs font-semibold">/{cmd.command}</code>
                                  </td>
                                  <td className="py-3 pr-4 text-gray-600 max-w-xs truncate">{cmd.prompt}</td>
                                  <td className="py-3 pr-4">
                                    <div className="flex flex-wrap gap-1">
                                      {(cmd.agent_ids || []).map(aid => {
                                        const ag = orgAgents.find(a => a.id === aid);
                                        return ag ? (
                                          <span key={aid} className="bg-blue-50 text-blue-700 px-2 py-0.5 rounded-full text-xs">{ag.name}</span>
                                        ) : null;
                                      })}
                                    </div>
                                  </td>
                                  <td className="py-3 text-right">
                                    <button onClick={() => openSlashEdit(cmd)} className="text-gray-400 hover:text-purple-600 mr-2" title={t('organization:slashCommands.edit')}>
                                      <Edit3 className="w-4 h-4" />
                                    </button>
                                    <button onClick={() => handleDeleteSlashCommand(cmd.id)} className="text-gray-400 hover:text-red-600" title={t('organization:slashCommands.delete')}>
                                      <Trash2 className="w-4 h-4" />
                                    </button>
                                  </td>
                                </tr>
                              ))}
                            </tbody>
                          </table>
                        </div>
                      )}
                    </div>
                  )}
                </div>
              )}
```

- [ ] **Step 6: Add the modal JSX**

Before the closing `</Layout>` tag (end of file), add:

```jsx
      {/* Slash Command Modal */}
      {slashModalOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-sm">
          <div className="bg-white rounded-2xl shadow-elevated w-full max-w-lg mx-4 p-6">
            <div className="flex items-center justify-between mb-6">
              <h3 className="text-lg font-heading font-bold text-gray-900">
                {slashEditItem ? t('organization:slashCommands.modal.editTitle') : t('organization:slashCommands.modal.createTitle')}
              </h3>
              <button onClick={() => setSlashModalOpen(false)} className="text-gray-400 hover:text-gray-600">
                <X className="w-5 h-5" />
              </button>
            </div>

            <div className="space-y-4">
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">{t('organization:slashCommands.modal.commandLabel')}</label>
                <div className="flex items-center border border-gray-200 rounded-lg overflow-hidden focus-within:ring-2 focus-within:ring-purple-500">
                  <span className="px-3 text-purple-600 font-bold bg-gray-50">/</span>
                  <input type="text" className="flex-1 px-3 py-2 text-sm outline-none"
                    placeholder={t('organization:slashCommands.modal.commandPlaceholder')}
                    value={slashForm.command}
                    onChange={e => setSlashForm(p => ({ ...p, command: e.target.value.replace(/[^a-zA-Z0-9_-]/g, '') }))} />
                </div>
              </div>

              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">{t('organization:slashCommands.modal.promptLabel')}</label>
                <textarea className="w-full px-3 py-2 border border-gray-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-purple-500 resize-none"
                  rows={4}
                  placeholder={t('organization:slashCommands.modal.promptPlaceholder')}
                  value={slashForm.prompt}
                  onChange={e => setSlashForm(p => ({ ...p, prompt: e.target.value }))} />
              </div>

              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">{t('organization:slashCommands.modal.companionsLabel')}</label>
                <div className="border border-gray-200 rounded-lg p-2 min-h-[40px] flex flex-wrap gap-1 items-center">
                  {slashForm.agent_ids.map(aid => {
                    const ag = orgAgents.find(a => a.id === aid);
                    return ag ? (
                      <span key={aid} className="bg-blue-50 text-blue-700 px-2 py-0.5 rounded-full text-xs flex items-center gap-1">
                        {ag.name}
                        <button onClick={() => setSlashForm(p => ({ ...p, agent_ids: p.agent_ids.filter(x => x !== aid) }))}
                          className="text-blue-400 hover:text-red-500">
                          <X className="w-3 h-3" />
                        </button>
                      </span>
                    ) : null;
                  })}
                  <select
                    className="text-sm text-gray-500 bg-transparent outline-none cursor-pointer"
                    value=""
                    onChange={e => {
                      const id = parseInt(e.target.value);
                      if (id && !slashForm.agent_ids.includes(id)) {
                        setSlashForm(p => ({ ...p, agent_ids: [...p.agent_ids, id] }));
                      }
                    }}
                  >
                    <option value="">{t('organization:slashCommands.modal.addCompanion')}</option>
                    {orgAgents.filter(a => !slashForm.agent_ids.includes(a.id)).map(a => (
                      <option key={a.id} value={a.id}>{a.name}</option>
                    ))}
                  </select>
                </div>
              </div>
            </div>

            <div className="flex justify-end gap-3 mt-6">
              <button onClick={() => setSlashModalOpen(false)}
                className="px-4 py-2 border border-gray-200 rounded-lg text-sm text-gray-600 hover:bg-gray-50 transition-colors">
                {t('organization:slashCommands.modal.cancel')}
              </button>
              <button onClick={handleSaveSlashCommand} disabled={slashLoading}
                className="px-4 py-2 bg-gradient-to-r from-purple-500 to-purple-600 hover:from-purple-600 hover:to-purple-700 text-white text-sm font-semibold rounded-button shadow-card transition-all disabled:opacity-50">
                {slashLoading ? <Loader2 className="w-4 h-4 animate-spin" /> : t('organization:slashCommands.modal.save')}
              </button>
            </div>
          </div>
        </div>
      )}
```

- [ ] **Step 7: Commit**

```bash
git add frontend/pages/organization.js
git commit -m "feat: add slash commands settings section to organization page"
```

---

### Task 5: Add i18n translation keys

**Files:**
- Modify: `frontend/public/locales/fr/organization.json`
- Modify: `frontend/public/locales/en/organization.json`

- [ ] **Step 1: Add French translation keys**

Add the `slashCommands` block to the French organization translations:

```json
"slashCommands": {
  "title": "Raccourcis Prompts",
  "description": "Configurez des commandes / pour envoyer des prompts prédéfinis à vos companions",
  "addButton": "Ajouter un raccourci",
  "empty": "Aucun raccourci configuré",
  "edit": "Modifier",
  "delete": "Supprimer",
  "deleteConfirm": "Supprimer ce raccourci ?",
  "created": "Raccourci créé",
  "updated": "Raccourci mis à jour",
  "deleted": "Raccourci supprimé",
  "table": {
    "command": "Commande",
    "prompt": "Prompt",
    "companions": "Companions"
  },
  "modal": {
    "createTitle": "Nouveau raccourci",
    "editTitle": "Modifier le raccourci",
    "commandLabel": "Nom de la commande",
    "commandPlaceholder": "analyse",
    "promptLabel": "Prompt",
    "promptPlaceholder": "Analyse moi les tendances sur l'IA sur les 6 derniers mois...",
    "companionsLabel": "Companions avec accès",
    "addCompanion": "+ Ajouter un companion",
    "cancel": "Annuler",
    "save": "Enregistrer"
  },
  "errors": {
    "requiredFields": "Le nom et le prompt sont obligatoires"
  }
}
```

- [ ] **Step 2: Add English translation keys**

Same structure in English:

```json
"slashCommands": {
  "title": "Prompt Shortcuts",
  "description": "Configure / commands to send predefined prompts to your companions",
  "addButton": "Add shortcut",
  "empty": "No shortcuts configured",
  "edit": "Edit",
  "delete": "Delete",
  "deleteConfirm": "Delete this shortcut?",
  "created": "Shortcut created",
  "updated": "Shortcut updated",
  "deleted": "Shortcut deleted",
  "table": {
    "command": "Command",
    "prompt": "Prompt",
    "companions": "Companions"
  },
  "modal": {
    "createTitle": "New shortcut",
    "editTitle": "Edit shortcut",
    "commandLabel": "Command name",
    "commandPlaceholder": "analyse",
    "promptLabel": "Prompt",
    "promptPlaceholder": "Analyze AI trends over the last 6 months...",
    "companionsLabel": "Companions with access",
    "addCompanion": "+ Add companion",
    "cancel": "Cancel",
    "save": "Save"
  },
  "errors": {
    "requiredFields": "Name and prompt are required"
  }
}
```

- [ ] **Step 3: Commit**

```bash
git add frontend/public/locales/fr/organization.json frontend/public/locales/en/organization.json
git commit -m "feat: add i18n keys for slash commands"
```

---

### Task 6: Add autocomplete menu to chat page

**Files:**
- Modify: `frontend/pages/chat/[agentId].js`

- [ ] **Step 1: Add state and data loading**

After the existing state declarations (around line 109), add:

```javascript
  const [slashCommands, setSlashCommands] = useState([]);
  const [showSlashMenu, setShowSlashMenu] = useState(false);
  const [slashFilter, setSlashFilter] = useState('');
  const [slashSelectedIdx, setSlashSelectedIdx] = useState(0);
```

In the existing `useEffect` that loads agent data (find the effect that runs when `agentId` changes), add a call to load slash commands after the agent is loaded. Add this function after `loadAgent`:

```javascript
  const loadSlashCommands = async (agId) => {
    try {
      const res = await api.get(`/api/companies/slash-commands?agent_id=${agId}`);
      setSlashCommands(res.data.slash_commands || []);
    } catch {
      setSlashCommands([]);
    }
  };
```

Call `loadSlashCommands(agentId)` in the same `useEffect` where `loadAgent(agentId)` is called.

- [ ] **Step 2: Modify the input onChange and onKeyDown handlers**

Replace the input's `onChange` handler (line 737):

```javascript
  onChange={e => {
    const val = e.target.value;
    setInput(val);
    if (val.startsWith('/') && val.length >= 1) {
      setSlashFilter(val.slice(1).toLowerCase());
      setShowSlashMenu(true);
      setSlashSelectedIdx(0);
    } else {
      setShowSlashMenu(false);
    }
  }}
```

Replace the input's `onKeyDown` handler (line 738):

```javascript
  onKeyDown={e => {
    if (showSlashMenu) {
      const filtered = slashCommands.filter(c => c.command.toLowerCase().startsWith(slashFilter));
      if (e.key === 'ArrowDown') {
        e.preventDefault();
        setSlashSelectedIdx(i => Math.min(i + 1, filtered.length - 1));
      } else if (e.key === 'ArrowUp') {
        e.preventDefault();
        setSlashSelectedIdx(i => Math.max(i - 1, 0));
      } else if (e.key === 'Enter' && filtered.length > 0) {
        e.preventDefault();
        handleSlashSelect(filtered[slashSelectedIdx]);
      } else if (e.key === 'Escape') {
        setShowSlashMenu(false);
      }
    } else if (e.key === 'Enter' && !e.shiftKey) {
      sendMessage();
    }
  }}
```

- [ ] **Step 3: Add the handleSlashSelect function and modify sendMessage**

Before `sendMessage`, add:

```javascript
  const handleSlashSelect = (cmd) => {
    setInput('/' + cmd.command);
    setShowSlashMenu(false);
    // Send immediately
    setTimeout(() => {
      sendSlashCommand(cmd);
    }, 0);
  };

  const sendSlashCommand = async (cmd) => {
    if (!selectedConv) return;
    setLoading(true);
    setInput('');

    // Display the /command as user message
    const userMsg = { role: 'user', content: '/' + cmd.command };
    setMessages(prev => [...prev, userMsg]);

    try {
      // Store the /command as user message
      await api.post(`/conversations/${selectedConv}/messages`, {
        conversation_id: selectedConv,
        role: 'user',
        content: '/' + cmd.command,
      });

      const resHist = await api.get(`/conversations/${selectedConv}/messages`);
      const history = resHist.data.map(m => ({ role: m.role, content: m.content }));

      // Send the actual prompt to /ask
      const resAsk = await api.post('/ask', {
        question: cmd.prompt,
        agent_id: agentId,
        history: history,
      });

      const assistantMsg = { role: 'agent', content: resAsk.data.answer };
      setMessages(prev => [...prev, assistantMsg]);

      await api.post(`/conversations/${selectedConv}/messages`, {
        conversation_id: selectedConv,
        role: 'agent',
        content: resAsk.data.answer,
      });
    } catch (err) {
      toast.error(err.response?.data?.detail || 'Error');
    } finally {
      setLoading(false);
    }
  };
```

- [ ] **Step 4: Add the autocomplete menu JSX**

Inside the input container `<div className="flex-1 relative">` (line 731), before the `<input>` element, add:

```jsx
                {showSlashMenu && (() => {
                  const filtered = slashCommands.filter(c => c.command.toLowerCase().startsWith(slashFilter));
                  return filtered.length > 0 ? (
                    <div className="absolute bottom-full left-0 right-0 mb-2 bg-white border border-gray-200 rounded-xl shadow-elevated overflow-hidden z-50">
                      <div className="px-3 py-2 border-b border-gray-100">
                        <span className="text-xs text-gray-400 font-medium">Commandes disponibles</span>
                      </div>
                      <div className="py-1">
                        {filtered.map((cmd, idx) => (
                          <button key={cmd.id} onClick={() => handleSlashSelect(cmd)}
                            className={`w-full flex items-center px-3 py-2.5 text-left transition-colors ${idx === slashSelectedIdx ? 'bg-purple-50' : 'hover:bg-gray-50'}`}>
                            <code className="text-purple-600 font-semibold text-sm min-w-[100px]">/{cmd.command}</code>
                            <span className="text-gray-400 text-sm truncate">{cmd.prompt}</span>
                          </button>
                        ))}
                      </div>
                    </div>
                  ) : null;
                })()}
```

- [ ] **Step 5: Also handle direct /command typing in sendMessage**

At the start of `sendMessage` (line 214), after the empty check, add slash command detection:

```javascript
    // Check if input is a slash command
    if (input.startsWith('/')) {
      const cmdName = input.slice(1).trim().toLowerCase();
      const cmd = slashCommands.find(c => c.command.toLowerCase() === cmdName);
      if (cmd) {
        setShowSlashMenu(false);
        sendSlashCommand(cmd);
        return;
      }
    }
```

- [ ] **Step 6: Commit**

```bash
git add frontend/pages/chat/[agentId].js
git commit -m "feat: add slash command autocomplete to chat input"
```

---

### Task 7: Manual testing and final verification

- [ ] **Step 1: Run backend lint**

Run: `cd backend && python -m ruff check .`
Expected: no errors in modified files

- [ ] **Step 2: Run frontend lint**

Run: `cd frontend && npm run lint`
Expected: no errors

- [ ] **Step 3: Run frontend build**

Run: `cd frontend && npm run build`
Expected: build succeeds

- [ ] **Step 4: Run backend tests**

Run: `cd backend && python -m pytest tests/ -v`
Expected: all existing tests pass

- [ ] **Step 5: Final commit (if any lint fixes needed)**

```bash
git add -A
git commit -m "fix: lint fixes for slash commands feature"
```
