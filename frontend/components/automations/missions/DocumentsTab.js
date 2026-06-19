import { useState, useEffect, useCallback, useRef } from 'react';
import { useTranslation } from 'next-i18next';
import toast from 'react-hot-toast';
import { Upload, FileText, Trash2 } from 'lucide-react';
import api from '../../../lib/api';

export default function DocumentsTab({ missionId }) {
  const { t } = useTranslation('automations');
  const [docs, setDocs] = useState([]);
  const [uploading, setUploading] = useState(false);
  const fileRef = useRef(null);

  const load = useCallback(async () => {
    try {
      const res = await api.get(`/api/automations/missions/${missionId}/documents`);
      setDocs(res.data.documents || []);
    } catch {
      toast.error(t('errors.loadFailed'));
    }
  }, [missionId, t]);

  useEffect(() => {
    load();
  }, [load]);

  const pollStatus = async (taskId) => {
    for (let i = 0; i < 60; i += 1) {
      // eslint-disable-next-line no-await-in-loop
      await new Promise((r) => setTimeout(r, 2000));
      try {
        // eslint-disable-next-line no-await-in-loop
        const res = await api.get(`/upload-status/${taskId}`);
        if (res.data.status === 'completed') return true;
        if (res.data.status === 'failed') return false;
      } catch {
        return false;
      }
    }
    return false;
  };

  const handleFile = async (e) => {
    const file = e.target.files?.[0];
    if (!file) return;
    setUploading(true);
    const form = new FormData();
    form.append('file', file);
    try {
      const res = await api.post(`/api/automations/missions/${missionId}/documents`, form, {
        headers: { 'Content-Type': 'multipart/form-data' },
      });
      if (res.data.task_id) {
        const ok = await pollStatus(res.data.task_id);
        if (!ok) throw new Error('failed');
      }
      toast.success(t('missions.documents.uploaded'));
      load();
    } catch {
      toast.error(t('errors.saveFailed'));
    } finally {
      setUploading(false);
      if (fileRef.current) fileRef.current.value = '';
    }
  };

  const deleteDoc = async (id) => {
    if (!window.confirm(t('missions.documents.deleteConfirm'))) return;
    try {
      await api.delete(`/api/automations/missions/${missionId}/documents/${id}`);
      load();
    } catch {
      toast.error(t('errors.saveFailed'));
    }
  };

  return (
    <div>
      <button
        onClick={() => fileRef.current?.click()}
        disabled={uploading}
        className="flex items-center gap-2 px-4 py-2 bg-primary-600 text-white text-sm font-semibold rounded-button hover:bg-primary-700 disabled:opacity-50 mb-4"
      >
        <Upload className="w-4 h-4" />
        {uploading ? t('missions.documents.uploading') : t('missions.documents.upload')}
      </button>
      <input
        ref={fileRef}
        type="file"
        className="hidden"
        accept=".pdf,.txt,.csv,.docx,.xlsx,.pptx,.json"
        onChange={handleFile}
      />

      {docs.length === 0 ? (
        <p className="text-sm text-gray-400 py-8 text-center">{t('missions.documents.empty')}</p>
      ) : (
        <div className="space-y-1.5">
          {docs.map((d) => (
            <div
              key={d.id}
              className="flex items-center gap-3 px-3 py-2 bg-white border border-gray-200 rounded-card"
            >
              <FileText className="w-4 h-4 text-gray-400 shrink-0" />
              <span className="flex-1 text-sm text-gray-800 truncate">{d.filename}</span>
              <button onClick={() => deleteDoc(d.id)} className="p-1 text-gray-300 hover:text-red-500">
                <Trash2 className="w-4 h-4" />
              </button>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
