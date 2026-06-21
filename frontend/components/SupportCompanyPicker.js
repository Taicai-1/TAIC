import { useState, useEffect } from 'react';
import api from '../lib/api';

// Support-only: pick the active company. Switching re-issues the session cookie
// (server-side) then reloads so the whole app reflects the chosen company.
export default function SupportCompanyPicker({ currentId }) {
  const [companies, setCompanies] = useState([]);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    api
      .get('/api/support/companies')
      .then((r) => setCompanies(r.data.companies || []))
      .catch(() => setCompanies([]));
  }, []);

  const onChange = async (e) => {
    const company_id = parseInt(e.target.value, 10);
    if (!company_id) return;
    setBusy(true);
    try {
      await api.post('/api/support/active-company', { company_id });
      window.location.reload();
    } catch {
      setBusy(false);
    }
  };

  return (
    <div className="px-2 mb-3">
      <label className="block text-[11px] uppercase text-gray-400 mb-1 px-1">Entreprise (support)</label>
      <select
        value={currentId || ''}
        onChange={onChange}
        disabled={busy}
        className="w-full text-sm border border-gray-200 rounded-md px-2 py-1.5 bg-white text-gray-700 focus:outline-none focus:ring-2 focus:ring-primary-500"
      >
        <option value="">— choisir —</option>
        {companies.map((c) => (
          <option key={c.id} value={c.id}>
            {c.name}
          </option>
        ))}
      </select>
    </div>
  );
}
