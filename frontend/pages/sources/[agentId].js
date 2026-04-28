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
      await api.post("/upload-url", { url: urlInput.trim(), agent_id: parseInt(agentId) });
      showToast(t("sources:toast.urlAddSuccess"));
      setUrlInput("");
      loadSources(agentId);
    } catch {
      showToast(t("sources:toast.urlAddError"), "error");
    } finally {
      setAddingUrl(false);
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

        {/* RAG Documents */}
        <section>
          <h2 className="text-lg font-semibold font-heading mb-4 flex items-center space-x-2">
            <FileText className="w-5 h-5 text-primary-600" />
            <span>{t("sources:sections.documents")}</span>
            <span className="text-sm text-gray-400 font-normal">({documents.length})</span>
          </h2>

          {documents.length === 0 ? (
            <div className="text-center py-12 text-gray-500 bg-white rounded-card border border-gray-200 shadow-card">
              <FileText className="w-10 h-10 mx-auto mb-3 opacity-50" />
              <p>{t("sources:documents.empty")}</p>
            </div>
          ) : (
            <div className="space-y-2">
              {documents.map((doc) => {
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
