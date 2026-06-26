import { useState, useEffect } from "react";
import { useRouter } from "next/router";
import { useTranslation } from "next-i18next";
import { serverSideTranslations } from "next-i18next/serverSideTranslations";
import {
  FileText,
  Download,
  Loader2,
  File,
  Globe,
  RefreshCw,
  Plus,
} from "lucide-react";
import Layout from "../../components/Layout";
import { useAuth } from "../../hooks/useAuth";
import api from "../../lib/api";

function getFileExtension(filename) {
  if (!filename) return "";
  return filename.split(".").pop().toUpperCase();
}

function getBadgeColor(ext) {
  switch (ext) {
    case "PDF": return "bg-red-100 text-red-700";
    case "DOCX":
    case "DOC": return "bg-blue-100 text-blue-700";
    case "TXT": return "bg-gray-100 text-gray-700";
    default: return "bg-purple-100 text-purple-700";
  }
}

export default function SourcesPage() {
  const router = useRouter();
  const { agentId } = router.query;
  const { t } = useTranslation(["sources", "common", "errors"]);
  const { user, loading: authLoading, authenticated } = useAuth();

  const [agentName, setAgentName] = useState("");
  const [documents, setDocuments] = useState([]);
  const [loading, setLoading] = useState(true);
  const [toast, setToast] = useState(null);
  const [canEdit, setCanEdit] = useState(false);
  const [urlInput, setUrlInput] = useState("");
  const [addingUrl, setAddingUrl] = useState(false);
  const [refreshingDocId, setRefreshingDocId] = useState(null);
  const [folders, setFolders] = useState([]);
  const [selectedFolderId, setSelectedFolderId] = useState(null); // null = "Sans dossier"
  const [newFolderName, setNewFolderName] = useState("");
  const [uploadFolderId, setUploadFolderId] = useState(null); // target folder for new sources

  useEffect(() => {
    if (!authenticated || !agentId) return;
    loadSources(agentId);
  }, [agentId, authenticated]);

  const showToast = (message, type = "success") => {
    setToast({ message, type });
    setTimeout(() => setToast(null), 4000);
  };

  const loadSources = async (id) => {
    try {
      setLoading(true);
      const res = await api.get(`/api/agents/${id}/sources`);
      setAgentName(res.data.agent_name || "");
      setDocuments(res.data.documents || []);
      setCanEdit(res.data.can_edit || false);
      setFolders(res.data.folders || []);
    } catch {
      showToast(t("errors:generic", "Error loading sources"), "error");
    } finally {
      setLoading(false);
    }
  };

  const handleDownload = async (docId, filename) => {
    try {
      const res = await api.get(`/documents/${docId}/download-url`);
      if (res.data.signed_url) {
        window.open(res.data.signed_url, "_blank");
      } else if (res.data.proxy_url) {
        const dlRes = await api.get(res.data.proxy_url, {
          responseType: "blob",
        });
        const url = window.URL.createObjectURL(dlRes.data);
        const a = document.createElement("a");
        a.href = url;
        a.download = filename || "document";
        document.body.appendChild(a);
        a.click();
        a.remove();
        window.URL.revokeObjectURL(url);
      }
    } catch {
      showToast(t("sources:toast.downloadError"), "error");
    }
  };

  const handleAddUrl = async (e) => {
    e.preventDefault();
    if (!urlInput.trim() || addingUrl) return;
    try {
      setAddingUrl(true);
      const res = await api.post("/upload-url", { url: urlInput.trim(), agent_id: parseInt(agentId) });
      // /upload-url has no folder field; place the new source via the move endpoint.
      if (uploadFolderId && res.data.document_id) {
        try {
          await api.put(`/api/agents/${agentId}/documents/${res.data.document_id}/folder`, {
            folder_id: Number(uploadFolderId),
          });
        } catch {
          /* non-fatal: source is created, just stays "Sans dossier" */
        }
      }
      showToast(t("sources:toast.urlAddSuccess"));
      setUrlInput("");
      loadSources(agentId);
    } catch {
      showToast(t("sources:toast.urlAddError"), "error");
    } finally {
      setAddingUrl(false);
    }
  };

  const reloadFolders = async () => {
    try {
      const res = await api.get(`/api/agents/${agentId}/folders`);
      setFolders(res.data.folders || []);
    } catch {
      showToast(t("errors:generic", "Error loading sources"), "error");
    }
  };

  const handleCreateFolder = async () => {
    const name = newFolderName.trim();
    if (!name) return;
    try {
      await api.post(`/api/agents/${agentId}/folders`, { name });
      setNewFolderName("");
      await reloadFolders();
    } catch (e) {
      showToast(e?.response?.data?.detail || t("sources:folders.createError", "Erreur lors de la création du dossier"), "error");
    }
  };

  const handleRenameFolder = async (folder) => {
    const name = window.prompt(t("sources:folders.renamePrompt", "Nouveau nom du dossier"), folder.name);
    if (!name || !name.trim()) return;
    try {
      await api.put(`/api/agents/${agentId}/folders/${folder.id}`, { name: name.trim() });
      await reloadFolders();
    } catch (e) {
      showToast(e?.response?.data?.detail || t("sources:folders.renameError", "Erreur lors du renommage"), "error");
    }
  };

  const handleToggleFolder = async (folder) => {
    try {
      await api.put(`/api/agents/${agentId}/folders/${folder.id}`, { is_active: !folder.is_active });
      await reloadFolders();
    } catch (e) {
      showToast(e?.response?.data?.detail || t("sources:folders.toggleError", "Erreur lors du changement d'état"), "error");
    }
  };

  const handleDeleteFolder = async (folder) => {
    if (!window.confirm(t("sources:folders.deleteConfirm", `Supprimer le dossier "${folder.name}" ?`))) return;
    try {
      await api.delete(`/api/agents/${agentId}/folders/${folder.id}`);
      if (selectedFolderId === folder.id) setSelectedFolderId(null);
      await reloadFolders();
    } catch (e) {
      showToast(e?.response?.data?.detail || t("sources:folders.deleteError", "Le dossier doit être vide pour être supprimé"), "error");
    }
  };

  const handleMoveDoc = async (docId, folderId) => {
    try {
      await api.put(`/api/agents/${agentId}/documents/${docId}/folder`, {
        folder_id: folderId === "" ? null : Number(folderId),
      });
      await loadSources(agentId);
    } catch (e) {
      showToast(e?.response?.data?.detail || t("sources:folders.moveError", "Erreur lors du déplacement"), "error");
    }
  };

  const handleRefreshUrl = async (docId) => {
    if (refreshingDocId) return;
    try {
      setRefreshingDocId(docId);
      const res = await api.post(`/documents/${docId}/refresh-url`);
      showToast(t("sources:toast.urlRefreshSuccess", { chunks: res.data.chunks }));
      loadSources(agentId);
    } catch {
      showToast(t("sources:toast.urlRefreshError"), "error");
    } finally {
      setRefreshingDocId(null);
    }
  };

  if (authLoading || loading) {
    return (
      <Layout showBack backHref="/agents" title={t("sources:pageTitle")}>
        <div className="flex items-center justify-center py-24">
          <div className="flex items-center space-x-3 text-gray-500">
            <Loader2 className="w-6 h-6 animate-spin" />
            <span>{t("sources:loading")}</span>
          </div>
        </div>
      </Layout>
    );
  }

  const visibleDocuments = documents.filter((d) =>
    selectedFolderId === null ? !d.agent_folder_id : d.agent_folder_id === selectedFolderId
  );

  return (
    <Layout showBack backHref="/agents" title={t("sources:pageTitle")}>
      {/* Toast */}
      {toast && (
        <div className={`fixed top-4 right-4 z-50 px-4 py-3 rounded-button shadow-card text-sm font-medium transition-all duration-300 ${
          toast.type === "error"
            ? "bg-red-600 text-white"
            : "bg-green-600 text-white"
        }`}>
          {toast.message}
        </div>
      )}

      <div className="max-w-5xl mx-auto px-4 py-8">
        {/* Agent name subtitle */}
        {agentName && <p className="text-sm text-gray-500 mb-6">{agentName}</p>}

        {/* URL Input */}
        {canEdit && (
          <form onSubmit={handleAddUrl} className="mb-6 flex items-center space-x-2">
            <div className="flex-1 relative">
              <Globe className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400" />
              <input
                type="url"
                value={urlInput}
                onChange={(e) => setUrlInput(e.target.value)}
                placeholder={t("sources:url.placeholder")}
                className="w-full pl-10 pr-4 py-2.5 border border-gray-200 rounded-input text-sm focus:outline-none focus:ring-2 focus:ring-primary-500 focus:border-transparent"
                disabled={addingUrl}
              />
            </div>
            <select
              value={uploadFolderId ?? ""}
              onChange={(e) => setUploadFolderId(e.target.value === "" ? null : Number(e.target.value))}
              className="px-3 py-2.5 border border-gray-200 rounded-input text-sm bg-white text-gray-600 focus:outline-none focus:ring-2 focus:ring-primary-500 focus:border-transparent"
              title={t("sources:folders.uploadTarget", "Dossier cible")}
              aria-label={t("sources:folders.uploadTarget", "Dossier cible")}
            >
              <option value="">{t("sources:folders.uncategorized", "Sans dossier")}</option>
              {folders.map((f) => (
                <option key={f.id} value={f.id}>{f.name}</option>
              ))}
            </select>
            <button
              type="submit"
              disabled={!urlInput.trim() || addingUrl}
              className="flex items-center space-x-1.5 px-4 py-2.5 bg-primary-600 hover:bg-primary-700 disabled:bg-gray-300 text-white text-sm font-medium rounded-button transition-colors"
            >
              {addingUrl ? (
                <>
                  <Loader2 className="w-4 h-4 animate-spin" />
                  <span>{t("sources:url.adding")}</span>
                </>
              ) : (
                <>
                  <Plus className="w-4 h-4" />
                  <span>{t("sources:url.add")}</span>
                </>
              )}
            </button>
          </form>
        )}

        {/* Folder bar */}
        <div className="mb-6">
          <div className="flex flex-wrap items-center gap-2">
            <button
              type="button"
              onClick={() => setSelectedFolderId(null)}
              className={`rounded-button border px-3 py-1.5 text-sm transition-colors ${
                selectedFolderId === null
                  ? "bg-primary-50 border-primary-300 text-primary-700"
                  : "bg-white border-gray-200 text-gray-600 hover:bg-gray-50"
              }`}
            >
              {t("sources:folders.uncategorized", "Sans dossier")}
            </button>
            {folders.map((f) => (
              <div
                key={f.id}
                onClick={() => setSelectedFolderId(f.id)}
                className={`group flex items-center rounded-button border px-3 py-1.5 text-sm cursor-pointer transition-colors ${
                  selectedFolderId === f.id
                    ? "bg-primary-50 border-primary-300 text-primary-700"
                    : "bg-white border-gray-200 text-gray-600 hover:bg-gray-50"
                } ${!f.is_active ? "opacity-50" : ""}`}
              >
                <span className="font-medium">{f.name}</span>
                <span className="ml-2 text-xs text-gray-400">{f.document_count}</span>
                {canEdit && (
                  <span className="ml-2 hidden group-hover:inline-flex items-center gap-1.5">
                    <button
                      type="button"
                      onClick={(ev) => { ev.stopPropagation(); handleToggleFolder(f); }}
                      className="text-gray-400 hover:text-gray-700"
                      title={f.is_active ? t("sources:folders.deactivate", "Désactiver") : t("sources:folders.activate", "Activer")}
                    >
                      {f.is_active ? "◉" : "○"}
                    </button>
                    <button
                      type="button"
                      onClick={(ev) => { ev.stopPropagation(); handleRenameFolder(f); }}
                      className="text-gray-400 hover:text-gray-700"
                      title={t("sources:folders.rename", "Renommer")}
                    >
                      ✎
                    </button>
                    <button
                      type="button"
                      onClick={(ev) => { ev.stopPropagation(); handleDeleteFolder(f); }}
                      className="text-red-400 hover:text-red-600"
                      title={t("sources:folders.delete", "Supprimer")}
                    >
                      🗑
                    </button>
                  </span>
                )}
              </div>
            ))}
          </div>
          {canEdit && (
            <div className="mt-3 flex items-center gap-2">
              <input
                type="text"
                value={newFolderName}
                onChange={(e) => setNewFolderName(e.target.value)}
                onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); handleCreateFolder(); } }}
                placeholder={t("sources:folders.newPlaceholder", "Nouveau dossier")}
                className="px-3 py-1.5 border border-gray-200 rounded-input text-sm focus:outline-none focus:ring-2 focus:ring-primary-500 focus:border-transparent"
              />
              <button
                type="button"
                onClick={handleCreateFolder}
                disabled={!newFolderName.trim()}
                className="flex items-center space-x-1 px-3 py-1.5 bg-primary-600 hover:bg-primary-700 disabled:bg-gray-300 text-white text-sm font-medium rounded-button transition-colors"
              >
                <Plus className="w-4 h-4" />
                <span>{t("sources:folders.create", "Créer")}</span>
              </button>
            </div>
          )}
        </div>

        {/* RAG Documents */}
        <section>
          <h2 className="text-lg font-semibold font-heading mb-4 flex items-center space-x-2">
            <FileText className="w-5 h-5 text-primary-600" />
            <span>{t("sources:sections.documents")}</span>
            <span className="text-sm text-gray-400 font-normal">({visibleDocuments.length})</span>
          </h2>

          {visibleDocuments.length === 0 ? (
            <div className="text-center py-12 text-gray-500 bg-white rounded-card border border-gray-200 shadow-card">
              <FileText className="w-10 h-10 mx-auto mb-3 opacity-50" />
              <p>{t("sources:documents.empty")}</p>
            </div>
          ) : (
            <div className="space-y-2">
              {visibleDocuments.map((doc) => {
                const ext = getFileExtension(doc.filename);
                const isNotion = !!doc.notion_link_id;
                const isUrl = !!doc.source_url;
                return (
                  <div
                    key={doc.id}
                    className="flex items-center justify-between p-4 bg-white border border-gray-200 rounded-card shadow-subtle hover:shadow-card transition-all"
                  >
                    <div className="flex items-center space-x-3 min-w-0">
                      {isUrl ? (
                        <Globe className="w-5 h-5 text-primary-500 flex-shrink-0" />
                      ) : (
                        <File className="w-5 h-5 text-gray-400 flex-shrink-0" />
                      )}
                      <div className="min-w-0">
                        <p className="text-sm font-medium text-gray-900 truncate">
                          {isUrl ? doc.source_url : doc.filename}
                        </p>
                        <p className="text-xs text-gray-500">
                          {doc.created_at ? new Date(doc.created_at).toLocaleDateString() : ""}
                        </p>
                      </div>
                      {isNotion ? (
                        <span className="px-2 py-0.5 text-xs rounded-full bg-purple-100 text-purple-700 border border-purple-200 flex-shrink-0">
                          {t("sources:documents.fromNotion")}
                        </span>
                      ) : isUrl ? (
                        <span className="px-2 py-0.5 text-xs rounded-full bg-blue-100 text-blue-700 border border-blue-200 flex-shrink-0">
                          {t("sources:documents.fromUrl")}
                        </span>
                      ) : (
                        <span className={`px-2 py-0.5 text-xs rounded-full flex-shrink-0 ${getBadgeColor(ext)}`}>
                          {ext}
                        </span>
                      )}
                    </div>
                    <div className="flex items-center space-x-2 flex-shrink-0 ml-4">
                      {canEdit && (
                        <select
                          value={doc.agent_folder_id ?? ""}
                          onChange={(e) => handleMoveDoc(doc.id, e.target.value)}
                          className="text-xs border border-gray-200 rounded-button px-2 py-1 bg-white text-gray-600"
                          title={t("sources:folders.moveTo", "Déplacer vers")}
                          aria-label={t("sources:folders.moveTo", "Déplacer vers")}
                        >
                          <option value="">{t("sources:folders.uncategorized", "Sans dossier")}</option>
                          {folders.map((f) => (
                            <option key={f.id} value={f.id}>{f.name}</option>
                          ))}
                        </select>
                      )}
                      {isUrl && canEdit && (
                        <button
                          onClick={() => handleRefreshUrl(doc.id)}
                          disabled={refreshingDocId === doc.id}
                          className="flex items-center space-x-1 px-3 py-1.5 text-xs bg-green-50 hover:bg-green-100 disabled:bg-gray-100 text-green-700 disabled:text-gray-400 rounded-button transition-colors border border-green-200 disabled:border-gray-200"
                        >
                          <RefreshCw className={`w-3.5 h-3.5 ${refreshingDocId === doc.id ? "animate-spin" : ""}`} />
                          <span>
                            {refreshingDocId === doc.id
                              ? t("sources:url.refreshing")
                              : t("sources:url.refresh")}
                          </span>
                        </button>
                      )}
                      {doc.has_file && (
                        <button
                          onClick={() => handleDownload(doc.id, doc.filename)}
                          className="flex items-center space-x-1 px-3 py-1.5 text-xs bg-primary-50 hover:bg-primary-100 text-primary-700 rounded-button transition-colors border border-primary-100"
                        >
                          <Download className="w-3.5 h-3.5" />
                          <span>{t("sources:documents.download")}</span>
                        </button>
                      )}
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </section>
      </div>
    </Layout>
  );
}

export async function getServerSideProps({ locale }) {
  return {
    props: {
      ...(await serverSideTranslations(locale, ["sources", "common", "errors"])),
    },
  };
}
