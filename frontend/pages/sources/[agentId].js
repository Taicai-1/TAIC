import { useState, useEffect } from "react";
import { useRouter } from "next/router";
import axios from "axios";
import { useTranslation } from "next-i18next";
import { serverSideTranslations } from "next-i18next/serverSideTranslations";
import {
  FileText,
  Download,
  Loader2,
  File,
} from "lucide-react";
import Layout from "../../components/Layout";

const getApiUrl = () => {
  if (process.env.NEXT_PUBLIC_API_URL) return process.env.NEXT_PUBLIC_API_URL;
  if (typeof window !== "undefined" && window.location.hostname.includes("run.app")) {
    return window.location.origin.replace("frontend", "backend");
  }
  return "http://localhost:8080";
};
const API_URL = getApiUrl();

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

  const [token, setToken] = useState(null);
  const [agentName, setAgentName] = useState("");
  const [documents, setDocuments] = useState([]);
  const [loading, setLoading] = useState(true);
  const [toast, setToast] = useState(null);

  useEffect(() => {
    const savedToken = localStorage.getItem("token");
    if (!savedToken) {
      router.push("/login");
      return;
    }
    setToken(savedToken);
    if (agentId) loadSources(agentId, savedToken);
  }, [agentId]);

  const showToast = (message, type = "success") => {
    setToast({ message, type });
    setTimeout(() => setToast(null), 4000);
  };

  const loadSources = async (id, authToken) => {
    try {
      setLoading(true);
      const res = await axios.get(`${API_URL}/api/agents/${id}/sources`, {
        headers: { Authorization: `Bearer ${authToken}` },
      });
      setAgentName(res.data.agent_name || "");
      setDocuments(res.data.documents || []);
    } catch {
      showToast(t("errors:generic", "Error loading sources"), "error");
    } finally {
      setLoading(false);
    }
  };

  const handleDownload = async (docId, filename) => {
    try {
      const res = await axios.get(`${API_URL}/documents/${docId}/download-url`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      if (res.data.signed_url) {
        window.open(res.data.signed_url, "_blank");
      } else if (res.data.proxy_url) {
        // Proxy needs auth header, so download via axios then trigger browser download
        const dlRes = await axios.get(`${API_URL}${res.data.proxy_url}`, {
          headers: { Authorization: `Bearer ${token}` },
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

  if (loading) {
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

        {/* RAG Documents */}
        <section>
          <h2 className="text-lg font-semibold font-heading mb-4 flex items-center space-x-2">
            <FileText className="w-5 h-5 text-blue-600" />
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
                return (
                  <div
                    key={doc.id}
                    className="flex items-center justify-between p-4 bg-white border border-gray-200 rounded-card shadow-subtle hover:shadow-card transition-all"
                  >
                    <div className="flex items-center space-x-3 min-w-0">
                      <File className="w-5 h-5 text-gray-400 flex-shrink-0" />
                      <div className="min-w-0">
                        <p className="text-sm font-medium text-gray-900 truncate">{doc.filename}</p>
                        <p className="text-xs text-gray-500">
                          {doc.created_at ? new Date(doc.created_at).toLocaleDateString() : ""}
                        </p>
                      </div>
                      {isNotion ? (
                        <span className="px-2 py-0.5 text-xs rounded-full bg-purple-100 text-purple-700 border border-purple-200 flex-shrink-0">
                          {t("sources:documents.fromNotion")}
                        </span>
                      ) : (
                        <span className={`px-2 py-0.5 text-xs rounded-full flex-shrink-0 ${getBadgeColor(ext)}`}>
                          {ext}
                        </span>
                      )}
                    </div>
                    <div className="flex items-center space-x-2 flex-shrink-0 ml-4">
                      {doc.has_file && (
                        <button
                          onClick={() => handleDownload(doc.id, doc.filename)}
                          className="flex items-center space-x-1 px-3 py-1.5 text-xs bg-blue-50 hover:bg-blue-100 text-blue-700 rounded-button transition-colors border border-blue-200"
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
