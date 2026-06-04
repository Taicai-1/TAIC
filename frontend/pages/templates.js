import { useState, useEffect, useCallback } from "react";
import { useRouter } from "next/router";
import toast, { Toaster } from "react-hot-toast";
import { useTranslation } from "next-i18next";
import { serverSideTranslations } from "next-i18next/serverSideTranslations";
import {
  Plus,
  LayoutTemplate,
  X,
  Trash2,
  Pencil,
  FileText,
  Zap,
  Search,
  Upload,
  Database,
  MessageCircle,
} from "lucide-react";
import Layout from "../components/Layout";
import { useAuth } from "../hooks/useAuth";
import api from "../lib/api";

export default function TemplatesPage() {
  const { t } = useTranslation(["templates", "common", "errors", "agents"]);
  const { user, loading: authLoading, authenticated } = useAuth();
  const router = useRouter();

  const [templates, setTemplates] = useState([]);
  const [loading, setLoading] = useState(true);
  const [showForm, setShowForm] = useState(false);
  const [editingTemplate, setEditingTemplate] = useState(null);
  const [selectedCategory, setSelectedCategory] = useState(null);
  const [orgDocuments, setOrgDocuments] = useState([]);
  const [docSearch, setDocSearch] = useState("");
  const [saving, setSaving] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [emailTagInput, setEmailTagInput] = useState("");
  const [form, setForm] = useState({
    name: "",
    description: "",
    category: "",
    icon: "",
    default_contexte: "",
    default_biographie: "",
    default_type: "conversationnel",
    document_ids: [],
    default_email_tags: [],
    default_neo4j_enabled: false,
    default_neo4j_person_name: "",
    default_neo4j_depth: 1,
    default_weekly_recap_enabled: false,
    default_weekly_recap_prompt: "",
    default_weekly_recap_recipients: [],
    default_recap_frequency: "weekly",
    default_recap_hour: 9,
  });

  const isAdmin = user?.role === "admin" || user?.role === "owner";

  const loadTemplates = useCallback(async () => {
    try {
      const resp = await api.get("/api/templates");
      setTemplates(resp.data.templates || []);
    } catch (error) {
      if (error.response?.status === 401) router.push("/login");
    } finally {
      setLoading(false);
    }
  }, [router]);

  const loadOrgDocuments = useCallback(async () => {
    try {
      const resp = await api.get("/user/documents");
      setOrgDocuments(resp.data.documents || []);
    } catch {
      // silent
    }
  }, []);

  useEffect(() => {
    if (!authenticated) return;
    loadTemplates();
    loadOrgDocuments();
  }, [authenticated, loadTemplates, loadOrgDocuments]);

  const categories = [...new Set(templates.map((t) => t.category).filter(Boolean))];

  const filteredTemplates = selectedCategory
    ? templates.filter((t) => t.category === selectedCategory)
    : templates;

  const filteredDocs = orgDocuments.filter((d) =>
    d.filename.toLowerCase().includes(docSearch.toLowerCase())
  );

  const resetForm = () => {
    setForm({
      name: "",
      description: "",
      category: "",
      icon: "",
      default_contexte: "",
      default_biographie: "",
      default_type: "conversationnel",
      document_ids: [],
      default_email_tags: [],
      default_neo4j_enabled: false,
      default_neo4j_person_name: "",
      default_neo4j_depth: 1,
      default_weekly_recap_enabled: false,
      default_weekly_recap_prompt: "",
      default_weekly_recap_recipients: [],
      default_recap_frequency: "weekly",
      default_recap_hour: 9,
    });
    setEditingTemplate(null);
    setDocSearch("");
    setEmailTagInput("");
  };

  const openCreate = () => {
    resetForm();
    setShowForm(true);
  };

  const openEdit = async (template) => {
    try {
      const resp = await api.get(`/api/templates/${template.id}`);
      const tmpl = resp.data.template;
      setForm({
        name: tmpl.name || "",
        description: tmpl.description || "",
        category: tmpl.category || "",
        icon: tmpl.icon || "",
        default_contexte: tmpl.default_contexte || "",
        default_biographie: tmpl.default_biographie || "",
        default_type: tmpl.default_type || "conversationnel",
        document_ids: (tmpl.documents || []).map((d) => d.id),
        default_email_tags: tmpl.default_email_tags || [],
        default_neo4j_enabled: tmpl.default_neo4j_enabled || false,
        default_neo4j_person_name: tmpl.default_neo4j_person_name || "",
        default_neo4j_depth: tmpl.default_neo4j_depth || 1,
        default_weekly_recap_enabled: tmpl.default_weekly_recap_enabled || false,
        default_weekly_recap_prompt: tmpl.default_weekly_recap_prompt || "",
        default_weekly_recap_recipients: tmpl.default_weekly_recap_recipients || [],
        default_recap_frequency: tmpl.default_recap_frequency || "weekly",
        default_recap_hour: tmpl.default_recap_hour != null ? tmpl.default_recap_hour : 9,
      });
      setEditingTemplate(tmpl);
      setShowForm(true);
    } catch {
      toast.error(t("templates:toast.updateError"));
    }
  };

  const handleSave = async () => {
    if (!form.name.trim()) {
      toast.error(t("templates:form.name.placeholder"));
      return;
    }
    setSaving(true);
    try {
      const payload = {
        name: form.name,
        description: form.description || null,
        category: form.category || null,
        icon: form.icon || null,
        default_contexte: form.default_contexte || null,
        default_biographie: form.default_biographie || null,
        default_type: form.default_type,
        document_ids: form.document_ids,
        default_email_tags: form.default_email_tags.length > 0 ? form.default_email_tags : null,
        default_neo4j_enabled: form.default_neo4j_enabled,
        default_neo4j_person_name: form.default_neo4j_person_name || null,
        default_neo4j_depth: form.default_neo4j_depth,
        default_weekly_recap_enabled: form.default_weekly_recap_enabled,
        default_weekly_recap_prompt: form.default_weekly_recap_prompt || null,
        default_weekly_recap_recipients: form.default_weekly_recap_recipients.length > 0 ? form.default_weekly_recap_recipients : null,
        default_recap_frequency: form.default_recap_frequency,
        default_recap_hour: form.default_recap_hour,
      };

      if (editingTemplate) {
        await api.put(`/api/templates/${editingTemplate.id}`, payload);
        toast.success(t("templates:toast.updateSuccess"));
      } else {
        await api.post("/api/templates", payload);
        toast.success(t("templates:toast.createSuccess"));
      }
      setShowForm(false);
      resetForm();
      loadTemplates();
    } catch {
      toast.error(
        editingTemplate
          ? t("templates:toast.updateError")
          : t("templates:toast.createError")
      );
    } finally {
      setSaving(false);
    }
  };

  const handleDelete = async (templateId) => {
    if (!confirm(t("templates:confirm.deleteMessage"))) return;
    try {
      await api.delete(`/api/templates/${templateId}`);
      toast.success(t("templates:toast.deleteSuccess"));
      loadTemplates();
    } catch {
      toast.error(t("templates:toast.deleteError"));
    }
  };

  const handleUseTemplate = (templateId) => {
    router.push(`/agents?template_id=${templateId}`);
  };

  const toggleDocSelection = (docId) => {
    setForm((f) => ({
      ...f,
      document_ids: f.document_ids.includes(docId)
        ? f.document_ids.filter((id) => id !== docId)
        : [...f.document_ids, docId],
    }));
  };

  const handleFileUpload = async (e) => {
    const files = Array.from(e.target.files || []);
    if (files.length === 0) return;
    setUploading(true);
    try {
      for (const file of files) {
        const fd = new FormData();
        fd.append("file", file);
        const resp = await api.post("/upload", fd, {
          headers: { "Content-Type": "multipart/form-data" },
        });
        const newDocId = resp.data.document_id;
        if (newDocId) {
          setForm((f) => ({
            ...f,
            document_ids: [...f.document_ids, newDocId],
          }));
        }
      }
      toast.success(t("templates:toast.uploadSuccess"));
      await loadOrgDocuments();
    } catch {
      toast.error(t("templates:toast.uploadError"));
    } finally {
      setUploading(false);
      e.target.value = "";
    }
  };

  if (authLoading || loading) {
    return (
      <Layout>
        <div className="flex items-center justify-center min-h-[60vh]">
          <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-primary-600"></div>
        </div>
      </Layout>
    );
  }

  return (
    <Layout>
      <Toaster position="top-right" />
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        {/* Header */}
        <div className="flex items-center justify-between mb-6">
          <div>
            <h1 className="text-2xl font-heading font-extrabold text-slate-900">
              {t("templates:page.title")}
            </h1>
            <p className="text-sm text-gray-500 mt-1">
              {t("templates:page.subtitle")}
            </p>
          </div>
          {isAdmin && (
            <button
              onClick={openCreate}
              className="flex items-center px-6 py-3 bg-primary-600 hover:bg-primary-700 text-white rounded-button font-semibold shadow-card hover:shadow-elevated transition-all"
            >
              <Plus className="w-5 h-5 mr-2" />
              {t("templates:buttons.createNew")}
            </button>
          )}
        </div>

        {/* Category filters */}
        {categories.length > 0 && (
          <div className="flex flex-wrap gap-2 mb-6">
            <button
              onClick={() => setSelectedCategory(null)}
              className={`px-4 py-1.5 rounded-full text-sm font-medium transition-colors ${
                !selectedCategory
                  ? "bg-primary-600 text-white"
                  : "bg-gray-100 text-gray-600 hover:bg-gray-200"
              }`}
            >
              {t("templates:filter.all")}
            </button>
            {categories.map((cat) => (
              <button
                key={cat}
                onClick={() => setSelectedCategory(cat)}
                className={`px-4 py-1.5 rounded-full text-sm font-medium transition-colors ${
                  selectedCategory === cat
                    ? "bg-primary-600 text-white"
                    : "bg-gray-100 text-gray-600 hover:bg-gray-200"
                }`}
              >
                {cat}
              </button>
            ))}
          </div>
        )}

        {/* Template grid */}
        {filteredTemplates.length === 0 ? (
          <div className="text-center py-16">
            <LayoutTemplate className="w-16 h-16 text-gray-300 mx-auto mb-4" />
            <h3 className="text-lg font-semibold text-gray-600">
              {t("templates:page.empty")}
            </h3>
            <p className="text-sm text-gray-400 mt-1">
              {t("templates:page.emptyDescription")}
            </p>
          </div>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
            {filteredTemplates.map((template) => (
              <div
                key={template.id}
                className="bg-white border border-gray-200 rounded-card shadow-card hover:shadow-elevated transition-all p-6 flex flex-col"
              >
                <div className="flex items-center gap-3 mb-3">
                  <div className="w-10 h-10 bg-primary-50 rounded-lg flex items-center justify-center">
                    <LayoutTemplate className="w-5 h-5 text-primary-600" />
                  </div>
                  <div className="flex-1 min-w-0">
                    <h3 className="font-semibold text-gray-900 truncate">
                      {template.name}
                    </h3>
                    {template.category && (
                      <span className="text-xs bg-gray-100 text-gray-600 px-2 py-0.5 rounded-full">
                        {template.category}
                      </span>
                    )}
                  </div>
                </div>

                {template.description && (
                  <p className="text-sm text-gray-500 mb-3 line-clamp-2">
                    {template.description}
                  </p>
                )}

                <div className="mt-auto flex items-center justify-between pt-3 border-t border-gray-100">
                  <span className="text-xs text-gray-400">
                    {t("templates:card.documents", {
                      count: template.document_count,
                    })}
                  </span>
                  <div className="flex gap-2">
                    {isAdmin && (
                      <>
                        <button
                          onClick={() => openEdit(template)}
                          className="p-1.5 text-gray-400 hover:text-primary-600 hover:bg-primary-50 rounded-md transition-colors"
                          title={t("templates:buttons.edit")}
                        >
                          <Pencil className="w-4 h-4" />
                        </button>
                        <button
                          onClick={() => handleDelete(template.id)}
                          className="p-1.5 text-gray-400 hover:text-red-600 hover:bg-red-50 rounded-md transition-colors"
                          title={t("templates:buttons.delete")}
                        >
                          <Trash2 className="w-4 h-4" />
                        </button>
                      </>
                    )}
                    <button
                      onClick={() => handleUseTemplate(template.id)}
                      className="px-3 py-1.5 bg-primary-600 hover:bg-primary-700 text-white text-xs font-medium rounded-button transition-colors"
                    >
                      {t("templates:buttons.createAgent")}
                    </button>
                  </div>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Create/Edit Modal */}
      {showForm && (
        <div className="fixed inset-0 bg-black/50 backdrop-blur-sm flex items-center justify-center z-[100] p-4">
          <div className="bg-white rounded-card shadow-floating p-8 w-full max-w-lg mx-auto max-h-[85vh] overflow-auto border border-gray-200 animate-fade-in">
            <div className="flex items-center justify-between mb-6">
              <h2 className="text-xl font-heading font-bold text-gray-900">
                {editingTemplate
                  ? t("templates:modal.titleEdit")
                  : t("templates:modal.titleCreate")}
              </h2>
              <button
                onClick={() => {
                  setShowForm(false);
                  resetForm();
                }}
                className="p-1.5 text-gray-400 hover:text-gray-600 hover:bg-gray-100 rounded-md transition-colors"
              >
                <X className="w-5 h-5" />
              </button>
            </div>
            <div className="space-y-4">
              {/* Name */}
              <div>
                <label className="text-sm font-medium text-gray-700 mb-1 block">
                  {t("templates:form.name.label")}
                </label>
                <input
                  type="text"
                  className="w-full px-4 py-3 border border-gray-200 rounded-input focus:border-primary-500 focus:ring-2 focus:ring-primary-100 transition-all outline-none bg-white"
                  placeholder={t("templates:form.name.placeholder")}
                  value={form.name}
                  onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))}
                />
              </div>

              {/* Description */}
              <div>
                <label className="text-sm font-medium text-gray-700 mb-1 block">
                  {t("templates:form.description.label")}
                </label>
                <textarea
                  className="w-full px-4 py-3 border border-gray-200 rounded-input focus:border-primary-500 focus:ring-2 focus:ring-primary-100 transition-all outline-none bg-white resize-none"
                  placeholder={t("templates:form.description.placeholder")}
                  rows="2"
                  value={form.description}
                  onChange={(e) => setForm((f) => ({ ...f, description: e.target.value }))}
                />
              </div>

              {/* Category + Icon */}
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <label className="text-sm font-medium text-gray-700 mb-1 block">
                    {t("templates:form.category.label")}
                  </label>
                  <input
                    type="text"
                    className="w-full px-4 py-3 border border-gray-200 rounded-input focus:border-primary-500 focus:ring-2 focus:ring-primary-100 transition-all outline-none bg-white"
                    placeholder={t("templates:form.category.placeholder")}
                    value={form.category}
                    onChange={(e) =>
                      setForm((f) => ({ ...f, category: e.target.value }))
                    }
                  />
                </div>
                <div>
                  <label className="text-sm font-medium text-gray-700 mb-1 block">
                    {t("templates:form.icon.label")}
                  </label>
                  <input
                    type="text"
                    className="w-full px-4 py-3 border border-gray-200 rounded-input focus:border-primary-500 focus:ring-2 focus:ring-primary-100 transition-all outline-none bg-white"
                    placeholder={t("templates:form.icon.placeholder")}
                    value={form.icon}
                    onChange={(e) =>
                      setForm((f) => ({ ...f, icon: e.target.value }))
                    }
                  />
                </div>
              </div>

              {/* Contexte */}
              <div>
                <label className="text-sm font-medium text-gray-700 mb-1 block">
                  {t("templates:form.contexte.label")}
                </label>
                <textarea
                  className="w-full px-4 py-3 border border-gray-200 rounded-input focus:border-primary-500 focus:ring-2 focus:ring-primary-100 transition-all outline-none bg-white resize-none"
                  placeholder={t("templates:form.contexte.placeholder")}
                  rows="4"
                  value={form.default_contexte}
                  onChange={(e) =>
                    setForm((f) => ({ ...f, default_contexte: e.target.value }))
                  }
                />
              </div>

              {/* Biographie */}
              <div>
                <label className="text-sm font-medium text-gray-700 mb-1 block">
                  {t("templates:form.biographie.label")}
                </label>
                <textarea
                  className="w-full px-4 py-3 border border-gray-200 rounded-input focus:border-primary-500 focus:ring-2 focus:ring-primary-100 transition-all outline-none bg-white resize-none"
                  placeholder={t("templates:form.biographie.placeholder")}
                  rows="2"
                  value={form.default_biographie}
                  onChange={(e) =>
                    setForm((f) => ({
                      ...f,
                      default_biographie: e.target.value,
                    }))
                  }
                />
              </div>

              {/* Type */}
              <div>
                <label className="text-sm font-medium text-gray-700 mb-1 block flex items-center">
                  <Zap className="w-4 h-4 mr-2 text-purple-600" />
                  {t("templates:form.type.label")}
                </label>
                <select
                  className="w-full px-4 py-3 border border-gray-200 rounded-input focus:border-primary-500 focus:ring-2 focus:ring-primary-100 transition-all outline-none bg-white font-medium"
                  value={form.default_type}
                  onChange={(e) =>
                    setForm((f) => ({ ...f, default_type: e.target.value }))
                  }
                >
                  <option value="conversationnel">
                    {t("agents:types.conversationnel.name")} -{" "}
                    {t("agents:types.conversationnel.description")}
                  </option>
                  <option value="recherche_live">
                    {t("agents:types.recherche_live.name")} -{" "}
                    {t("agents:types.recherche_live.description")}
                  </option>
                  <option value="visuel">
                    {t("agents:types.visuel.name")} -{" "}
                    {t("agents:types.visuel.description")}
                  </option>
                  <option value="actionnable">
                    {t("agents:types.actionnable.name")} -{" "}
                    {t("agents:types.actionnable.description")}
                  </option>
                </select>
              </div>

              {/* Email Tags */}
              <div>
                <label className="text-sm font-medium text-gray-700 mb-1 block flex items-center">
                  <MessageCircle className="w-4 h-4 mr-2 text-purple-600" />
                  {t("templates:form.emailTags.label")}
                </label>
                <div className="flex flex-wrap gap-2 mb-2">
                  {(form.default_email_tags || []).map((tag, index) => (
                    <span
                      key={index}
                      className="inline-flex items-center px-3 py-1 bg-purple-100 text-purple-700 rounded-full text-sm font-medium"
                    >
                      {tag}
                      <button
                        type="button"
                        onClick={() => {
                          setForm((f) => ({
                            ...f,
                            default_email_tags: f.default_email_tags.filter((_, i) => i !== index),
                          }));
                        }}
                        className="ml-2 text-purple-500 hover:text-purple-700"
                      >
                        ×
                      </button>
                    </span>
                  ))}
                </div>
                <div className="flex gap-2">
                  <input
                    type="text"
                    className="flex-1 px-4 py-2 border border-gray-200 rounded-input focus:border-purple-500 focus:ring-2 focus:ring-purple-200 transition-all outline-none bg-white text-sm"
                    placeholder={t("templates:form.emailTags.placeholder")}
                    value={emailTagInput}
                    onChange={(e) => setEmailTagInput(e.target.value)}
                    onKeyDown={(e) => {
                      if (e.key === "Enter" && emailTagInput.trim()) {
                        e.preventDefault();
                        const newTag = `@${emailTagInput.trim().toLowerCase().replace(/^@/, "")}`;
                        if (!form.default_email_tags.includes(newTag)) {
                          setForm((f) => ({
                            ...f,
                            default_email_tags: [...(f.default_email_tags || []), newTag],
                          }));
                        }
                        setEmailTagInput("");
                      }
                    }}
                  />
                  <button
                    type="button"
                    onClick={() => {
                      if (emailTagInput.trim()) {
                        const newTag = `@${emailTagInput.trim().toLowerCase().replace(/^@/, "")}`;
                        if (!form.default_email_tags.includes(newTag)) {
                          setForm((f) => ({
                            ...f,
                            default_email_tags: [...(f.default_email_tags || []), newTag],
                          }));
                        }
                        setEmailTagInput("");
                      }
                    }}
                    className="px-4 py-2 bg-purple-600 text-white rounded-button hover:bg-purple-700 transition-colors text-sm font-medium"
                  >
                    +
                  </button>
                </div>
              </div>

              {/* Neo4j Knowledge Graph */}
              <div className="p-4 bg-gradient-to-br from-teal-50 to-cyan-50 rounded-button border border-teal-200">
                <div className="flex items-center justify-between mb-3">
                  <label className="text-sm font-medium text-gray-700 flex items-center">
                    <Database className="w-4 h-4 mr-2 text-teal-600" />
                    {t("templates:form.neo4j.label")}
                  </label>
                  <button
                    type="button"
                    className={`w-14 h-7 flex items-center rounded-full px-1 transition-colors duration-200 focus:outline-none border border-teal-600 ${form.default_neo4j_enabled ? "bg-teal-600" : "bg-gray-200"}`}
                    onClick={() => setForm((f) => ({ ...f, default_neo4j_enabled: !f.default_neo4j_enabled }))}
                  >
                    <span className={`h-5 w-5 rounded-full shadow transition-transform duration-200 ${form.default_neo4j_enabled ? "bg-white translate-x-7" : "bg-gray-400 translate-x-0"}`} />
                  </button>
                </div>
                {form.default_neo4j_enabled && (
                  <div className="space-y-3 mt-3">
                    <div>
                      <label className="text-xs font-medium text-gray-600 mb-1 block">{t("templates:form.neo4j.person")}</label>
                      <input
                        type="text"
                        className="w-full px-3 py-2 border border-teal-200 rounded-sm focus:border-teal-500 focus:ring-2 focus:ring-teal-200 transition-all outline-none bg-white text-sm"
                        placeholder={t("templates:form.neo4j.personPlaceholder")}
                        value={form.default_neo4j_person_name}
                        onChange={(e) => setForm((f) => ({ ...f, default_neo4j_person_name: e.target.value }))}
                      />
                    </div>
                    <div>
                      <label className="text-xs font-medium text-gray-600 mb-1 block">{t("templates:form.neo4j.depth")}</label>
                      <select
                        className="w-full px-3 py-2 border border-teal-200 rounded-sm focus:border-teal-500 focus:ring-2 focus:ring-teal-200 transition-all outline-none bg-white text-sm"
                        value={form.default_neo4j_depth}
                        onChange={(e) => setForm((f) => ({ ...f, default_neo4j_depth: parseInt(e.target.value) }))}
                      >
                        <option value={1}>{t("templates:form.neo4j.depth1")}</option>
                        <option value={2}>{t("templates:form.neo4j.depth2")}</option>
                      </select>
                    </div>
                  </div>
                )}
              </div>

              {/* Weekly Recap */}
              <div className="p-4 bg-gradient-to-br from-amber-50 to-orange-50 rounded-button border border-amber-200">
                <div className="flex items-center justify-between mb-1">
                  <label className="text-sm font-medium text-gray-700 flex items-center">
                    <FileText className="w-4 h-4 mr-2 text-amber-600" />
                    {t("templates:form.recap.label")}
                  </label>
                  <button
                    type="button"
                    className={`w-14 h-7 flex items-center rounded-full px-1 transition-colors duration-200 focus:outline-none border border-amber-500 ${form.default_weekly_recap_enabled ? "bg-amber-500" : "bg-gray-200"}`}
                    onClick={() => setForm((f) => ({ ...f, default_weekly_recap_enabled: !f.default_weekly_recap_enabled }))}
                  >
                    <span className={`h-5 w-5 rounded-full shadow transition-transform duration-200 ${form.default_weekly_recap_enabled ? "bg-white translate-x-7" : "bg-gray-400 translate-x-0"}`} />
                  </button>
                </div>
                <p className="text-xs text-gray-500 mb-3">{t("templates:form.recap.helpText")}</p>
                {form.default_weekly_recap_enabled && (
                  <div className="space-y-3 mt-3">
                    <div>
                      <label className="text-xs font-medium text-gray-600 mb-1 block">{t("templates:form.recap.prompt")}</label>
                      <textarea
                        className="w-full px-3 py-2 border border-amber-200 rounded-sm focus:border-amber-500 focus:ring-2 focus:ring-amber-200 transition-all outline-none bg-white text-sm resize-none"
                        rows="2"
                        placeholder={t("templates:form.recap.promptPlaceholder")}
                        value={form.default_weekly_recap_prompt}
                        onChange={(e) => setForm((f) => ({ ...f, default_weekly_recap_prompt: e.target.value }))}
                      />
                    </div>
                    <div className="grid grid-cols-2 gap-3">
                      <div>
                        <label className="text-xs font-medium text-gray-600 mb-1 block">{t("templates:form.recap.frequency")}</label>
                        <select
                          className="w-full px-3 py-2 border border-amber-200 rounded-sm focus:border-amber-500 focus:ring-2 focus:ring-amber-200 transition-all outline-none bg-white text-sm"
                          value={form.default_recap_frequency}
                          onChange={(e) => setForm((f) => ({ ...f, default_recap_frequency: e.target.value }))}
                        >
                          <option value="daily">{t("templates:form.recap.daily")}</option>
                          <option value="weekly">{t("templates:form.recap.weekly")}</option>
                          <option value="monthly">{t("templates:form.recap.monthly")}</option>
                        </select>
                      </div>
                      <div>
                        <label className="text-xs font-medium text-gray-600 mb-1 block">{t("templates:form.recap.hour")}</label>
                        <select
                          className="w-full px-3 py-2 border border-amber-200 rounded-sm focus:border-amber-500 focus:ring-2 focus:ring-amber-200 transition-all outline-none bg-white text-sm"
                          value={form.default_recap_hour}
                          onChange={(e) => setForm((f) => ({ ...f, default_recap_hour: parseInt(e.target.value) }))}
                        >
                          {Array.from({ length: 24 }, (_, i) => (
                            <option key={i} value={i}>{String(i).padStart(2, "0")}:00</option>
                          ))}
                        </select>
                      </div>
                    </div>
                  </div>
                )}
              </div>

              {/* Document picker */}
              <div>
                <div className="flex items-center justify-between mb-1">
                  <label className="text-sm font-medium text-gray-700 flex items-center">
                    <FileText className="w-4 h-4 mr-2 text-primary-600" />
                    {t("templates:form.documents.label")}
                  </label>
                  <label className={`inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-button transition-colors cursor-pointer ${uploading ? "bg-gray-100 text-gray-400" : "bg-primary-50 text-primary-600 hover:bg-primary-100"}`}>
                    {uploading ? (
                      <div className="animate-spin rounded-full h-3 w-3 border-b-2 border-primary-600"></div>
                    ) : (
                      <Upload className="w-3.5 h-3.5" />
                    )}
                    {t("templates:form.documents.upload")}
                    <input
                      type="file"
                      multiple
                      accept=".pdf,.docx,.pptx,.xlsx,.txt,.csv,.json"
                      className="hidden"
                      onChange={handleFileUpload}
                      disabled={uploading}
                    />
                  </label>
                </div>
                {form.document_ids.length > 0 && (
                  <p className="text-xs text-primary-600 mb-2">
                    {t("templates:form.documents.selected", {
                      count: form.document_ids.length,
                    })}
                  </p>
                )}
                <div className="relative mb-2">
                  <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400" />
                  <input
                    type="text"
                    className="w-full pl-9 pr-4 py-2 border border-gray-200 rounded-input focus:border-primary-500 focus:ring-2 focus:ring-primary-100 transition-all outline-none bg-white text-sm"
                    placeholder={t("templates:form.documents.search")}
                    value={docSearch}
                    onChange={(e) => setDocSearch(e.target.value)}
                  />
                </div>
                <div className="max-h-40 overflow-auto border border-gray-200 rounded-input">
                  {filteredDocs.length === 0 ? (
                    <p className="text-xs text-gray-400 p-3 text-center">
                      {t("templates:form.documents.noDocuments")}
                    </p>
                  ) : (
                    filteredDocs.map((doc) => (
                      <label
                        key={doc.id}
                        className="flex items-center gap-3 px-3 py-2 hover:bg-gray-50 cursor-pointer border-b border-gray-100 last:border-0"
                      >
                        <input
                          type="checkbox"
                          checked={form.document_ids.includes(doc.id)}
                          onChange={() => toggleDocSelection(doc.id)}
                          className="rounded border-gray-300 text-primary-600 focus:ring-primary-500"
                        />
                        <span className="text-sm text-gray-700 truncate">
                          {doc.filename}
                        </span>
                      </label>
                    ))
                  )}
                </div>
              </div>
            </div>

            {/* Actions */}
            <div className="flex space-x-4 mt-8">
              <button
                onClick={() => {
                  setShowForm(false);
                  resetForm();
                }}
                className="flex-1 px-6 py-3 text-gray-700 bg-white border border-gray-200 rounded-button hover:bg-gray-50 hover:border-gray-300 transition-all font-medium"
              >
                {t("templates:buttons.cancel")}
              </button>
              <button
                onClick={handleSave}
                disabled={saving}
                className="flex-1 px-6 py-3 bg-primary-600 hover:bg-primary-700 text-white rounded-button transition-all font-semibold shadow-card hover:shadow-elevated disabled:opacity-50 disabled:cursor-not-allowed"
              >
                {saving ? (
                  <div className="flex items-center justify-center">
                    <div className="animate-spin rounded-full h-5 w-5 border-b-2 border-white mr-2"></div>
                    {t("common:states.saving")}
                  </div>
                ) : (
                  t("templates:buttons.save")
                )}
              </button>
            </div>
          </div>
        </div>
      )}
    </Layout>
  );
}

export async function getServerSideProps({ locale }) {
  return {
    props: {
      ...(await serverSideTranslations(locale, [
        "templates",
        "common",
        "errors",
        "agents",
      ])),
    },
  };
}
