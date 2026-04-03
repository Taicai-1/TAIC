import { useState, useEffect, useRef } from "react";
import { useRouter } from "next/router";
import Link from "next/link";
import { useTranslation } from 'next-i18next';
import { serverSideTranslations } from 'next-i18next/serverSideTranslations';
import { useAuth } from '../../hooks/useAuth';
import api from '../../lib/api';
import {
  Pencil,
  Trash2,
  Plus,
  Send,
  Mic,
  Paperclip,
  ArrowLeft,
  Bot,
  MessageCircle,
  Zap,
  FileText,
  Loader2,
  ThumbsUp,
  Copy,
  ExternalLink
} from "lucide-react";
import ReactMarkdown from "react-markdown";

// Image block rendered inside markdown (generated images)
const MarkdownImage = ({ src, alt, t }) => (
  <div className="my-3">
    <img src={src} alt={alt} className="max-w-full rounded-xl shadow-lg border border-gray-200"
         style={{ maxHeight: '512px', objectFit: 'contain' }} loading="lazy" />
    <div className="flex gap-2 mt-2">
      <a href={src} download className="px-3 py-1.5 bg-blue-600 text-white rounded-lg hover:bg-blue-700 text-sm">
        {t('chat:messages.downloadImage')}
      </a>
      <button className="px-3 py-1.5 bg-gray-200 text-gray-800 rounded-lg hover:bg-gray-300 text-sm"
              onClick={() => window.open(src, '_blank')}>
        {t('chat:messages.fullSize')}
      </button>
    </div>
  </div>
);

// Composant pour afficher du texte avec Markdown (safe by default, no dangerouslySetInnerHTML)
const MarkdownText = ({ children }) => {
  const { t } = useTranslation(['chat']);
  if (!children) return null;
  return (
    <div className="leading-relaxed markdown-content">
      <ReactMarkdown
        components={{
          strong: ({ node, ...props }) => <strong {...props} />,
          em: ({ node, ...props }) => <em {...props} />,
          code: ({ node, ...props }) => (
            <code className="px-1 py-0.5 bg-gray-100 rounded text-sm" {...props} />
          ),
          ul: ({ node, ...props }) => (
            <ul className="list-disc list-inside my-2" style={{ lineHeight: 1.4 }} {...props} />
          ),
          li: ({ node, ...props }) => <li className="ml-4" {...props} />,
          p: ({ node, ...props }) => <p className="mb-1" {...props} />,
          a: ({ node, ...props }) => (
            <a className="text-blue-600 hover:underline" target="_blank" rel="noopener noreferrer" {...props} />
          ),
          img: ({ node, ...props }) => <MarkdownImage {...props} t={t} />,
        }}
      >
        {children}
      </ReactMarkdown>
    </div>
  );
};

export default function AgentChatPage() {
  const router = useRouter();
  const { t } = useTranslation(['chat', 'common', 'errors']);
  const { user, loading: authLoading, authenticated } = useAuth();

  // Charge les infos de l'agent (doit être dans le scope du composant pour accéder à router)
  const loadAgent = async (id) => {
    try {
      const res = await api.get('/agents');
      const found = res.data.agents?.find(a => a.id.toString() === id.toString());
      if (!found) router.push("/agents");
      setAgent(found);
    } catch (e) {
      router.push("/agents");
    }
  };
  const { agentId } = router.query;
  const [agent, setAgent] = useState(null);
  const [conversations, setConversations] = useState([]);
  const [selectedConv, setSelectedConv] = useState(null);
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState("");
  const [listening, setListening] = useState(false);
  const recognitionRef = useRef(null);
  const [transcript, setTranscript] = useState("");
  const [baseInput, setBaseInput] = useState("");
  const [loading, setLoading] = useState(false);
  const chatEndRef = useRef(null);
  const [creatingConv, setCreatingConv] = useState(false);
  const [editingTitleId, setEditingTitleId] = useState(null);
  const [editedTitle, setEditedTitle] = useState("");
  const [newConvTitle, setNewConvTitle] = useState("");
  // Pièces jointes
  const [attachments, setAttachments] = useState([]);
  const [uploadingAttachments, setUploadingAttachments] = useState(false);

  useEffect(() => {
    if (!authenticated && !authLoading) router.push("/login");
    if (authenticated && agentId) {
      loadAgent(agentId);
      loadConversations(agentId, true); // pass flag to auto-create if none
    }
    // Cleanup on unmount
    return () => {
      try {
        if (recognitionRef.current) {
          recognitionRef.current.stop();
          recognitionRef.current = null;
        }
      } catch (e) {}
    };
  }, [agentId, authenticated, authLoading]);

  // Update input with transcript while listening
  useEffect(() => {
    if (listening) {
      setInput(baseInput + (baseInput && transcript ? ' ' : '') + transcript);
    }
  }, [baseInput, transcript, listening]);
  const loadConversations = async (agentId, autoCreateIfNone = false, autoSelect = true) => {
    try {
      const res = await api.get(`/conversations?agent_id=${agentId}`);
      setConversations(res.data);
      if (autoSelect) {
        if (res.data.length > 0) {
          await selectConversation(res.data[0].id);
        } else if (autoCreateIfNone) {
          // Auto-create first conversation for this agent
          await handleNewConversation(true);
        }
      }
    } catch (e) {
      setConversations([]);
    }
  };

  const selectConversation = async (convId) => {
    setSelectedConv(convId);
    setMessages([]);
    try {
      const res = await api.get(`/conversations/${convId}/messages`);
      setMessages(res.data);
    } catch (e) {
      setMessages([]);
    }
  };

  const handleNewConversation = async (auto = false) => {
    setCreatingConv(true);
  const convCount = conversations.length + 1;
  const convTitle = `${t('chat:sidebar.conversationNumber')} ${convCount}`;
    try {
      const res = await api.post('/conversations', {
        agent_id: agentId,
        title: convTitle
      });
      setCreatingConv(false);

      if (res.data.conversation_id) {
        setSelectedConv(res.data.conversation_id);
        setMessages([]);
        // Recharge les conversations sans auto-sélection
        await loadConversations(agentId, false, false);
      }
    } catch (e) {
      setCreatingConv(false);
    }
  };

const handleEditTitle = async (convId) => {
  try {
    await api.put(`/conversations/${convId}/title`, { title: editedTitle });
    setEditingTitleId(null);
    setEditedTitle("");
    await loadConversations(agentId);
  } catch {}
};

const handleDeleteConversation = async (convId) => {
  if (!window.confirm(t('chat:sidebar.deleteConfirmation'))) return;
  try {
    await api.delete(`/conversations/${convId}`);
    await loadConversations(agentId);
    if (selectedConv === convId) {
      setSelectedConv(null);
      setMessages([]);
    }
  } catch {}
};

  const sendMessage = async () => {
    if ((!input.trim() && attachments.length === 0) || !selectedConv) return;
    // Ajoute immédiatement le message utilisateur dans le state
    let userMsgContent = input;
    let extractedText = "";
    setLoading(true);
    setInput("");

    // Si pièce jointe, upload et extraction (un seul fichier)
    if (attachments.length > 0) {
      setUploadingAttachments(true);
      const formData = new FormData();
      formData.append("file", attachments[0]);
      try {
        const res = await api.post('/api/agent/extractText', formData, {
          headers: { 'Content-Type': 'multipart/form-data' },
        });
        extractedText = res.data.text || "";
        // Tronquer le texte extrait pour éviter de dépasser la limite de tokens LLM
        const MAX_ATTACHMENT_CHARS = 12000;
        if (extractedText.length > MAX_ATTACHMENT_CHARS) {
          extractedText = extractedText.slice(0, MAX_ATTACHMENT_CHARS) + "\n\n[... document tronqué]";
        }
      } catch (e) {
        extractedText = t('chat:messages.attachmentError');
      }
      setUploadingAttachments(false);
      setAttachments([]);
    }
    // Construit le prompt avec le texte extrait
    const finalPrompt = extractedText ? `${userMsgContent}\n\n---\n${t('chat:messages.attachmentContentLabel')}\n${extractedText}` : userMsgContent;
    const userMsg = { role: "user", content: finalPrompt };
    setMessages(prev => [...prev, userMsg]);
    try {
      // Ajoute le message utilisateur côté backend
      await api.post(`/conversations/${selectedConv}/messages`, {
        conversation_id: selectedConv,
        role: "user",
        content: finalPrompt
      });

      // Récupère l'historique de la conversation pour vérifier si c'est le premier message
      const resHist = await api.get(`/conversations/${selectedConv}/messages`);
      const history = resHist.data.map(m => ({ role: m.role, content: m.content }));

      // Si c'est le premier message (seulement 1 message dans l'historique), mettre à jour le titre
      if (resHist.data.length === 1) {
        const firstMsgTitle = finalPrompt.length > 50 ? finalPrompt.slice(0, 50) + "..." : finalPrompt;
        await api.put(`/conversations/${selectedConv}/title`, { title: firstMsgTitle });
        // Recharge la liste sans re-sélectionner
        await loadConversations(agentId, false, false);
      }

      // Appel à l'API /ask pour générer la réponse IA
      const resAsk = await api.post('/ask', {
        question: finalPrompt,
        agent_id: agentId,
        history: history
      });
      const iaAnswer = resAsk.data.answer || t('chat:messages.aiError');

      // Ajoute la réponse IA comme message d'agent côté backend
      const agentMsgRes = await api.post(`/conversations/${selectedConv}/messages`, {
        conversation_id: selectedConv,
        role: "agent",
        content: iaAnswer
      });

      // Ajoute la réponse IA aux messages locaux immédiatement
      const agentMsg = {
        id: agentMsgRes.data.message_id,
        role: "agent",
        content: iaAnswer
      };
      setMessages(prev => [...prev, agentMsg]);

      // Handle any action_results returned by the /ask endpoint and persist them as system messages
      const actionResults = resAsk.data.action_results || [];
      for (const ar of actionResults) {
        try {
          let content = "";
          if (ar && ar.result) {
            if (ar.result.status === "ok" && ar.result.result) {
              const r = ar.result.result;
              if (r.url) {
                content = `${t('chat:messages.actionExecuted', { action: ar.action })}: ${r.url}`;
              } else if (r.document_id) {
                content = `${t('chat:messages.actionExecuted', { action: ar.action })}: ${t('chat:messages.documentId')} ${r.document_id}`;
              } else if (r.path) {
                content = `${t('chat:messages.actionExecuted', { action: ar.action })}: ${t('chat:messages.fileCreated')} ${r.path}`;
              } else {
                content = `${t('chat:messages.actionExecuted', { action: ar.action })}: ${JSON.stringify(r)}`;
              }
            } else if (ar.result.status === "error") {
              content = `${t('chat:messages.actionError', { action: ar.action })}: ${ar.result.error || JSON.stringify(ar.result)}`;
            } else {
              content = `${t('chat:messages.actionExecuted', { action: ar.action })}: ${JSON.stringify(ar.result)}`;
            }
          } else {
            content = `${t('chat:messages.actionExecuted', { action: ar.action })}: ${JSON.stringify(ar)}`;
          }

          const systemMsgRes = await api.post(`/conversations/${selectedConv}/messages`, {
            conversation_id: selectedConv,
            role: "system",
            content: content
          });

          // Ajoute le message système aux messages locaux
          setMessages(prev => [...prev, {
            id: systemMsgRes.data.message_id,
            role: "system",
            content: content
          }]);
        } catch (e) {}
      }

      // Recharge juste la liste des conversations pour mettre à jour les titres (sans re-sélectionner)
      await loadConversations(agentId, false, false);
    } catch (e) {
      const errorMsg = { role: "agent", content: t('chat:messages.aiError') };
      setMessages(prev => [...prev, errorMsg]);
    } finally {
      setLoading(false);
      setTimeout(() => chatEndRef.current?.scrollIntoView({ behavior: "smooth" }), 100);
    }
  };

  useEffect(() => {
    setTimeout(() => chatEndRef.current?.scrollIntoView({ behavior: "smooth" }), 100);
  }, [messages]);

  // Fonctions de reconnaissance vocale
  const startListening = () => {
    if (!('webkitSpeechRecognition' in window) && !('SpeechRecognition' in window)) {
      alert(t('chat:voiceRecognition.notSupportedAlert'));
      return;
    }
    const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
    const recognition = new SpeechRecognition();
    recognition.lang = router.locale === 'en' ? 'en-US' : 'fr-FR';
    recognition.continuous = true;
    recognition.interimResults = true;

    setBaseInput(input);
    setTranscript('');

    recognition.onresult = (event) => {
      let interim = '';
      for (let i = event.resultIndex; i < event.results.length; i++) {
        if (event.results[i].isFinal) {
          setBaseInput(prev => prev + (prev ? ' ' : '') + event.results[i][0].transcript);
        } else {
          interim += event.results[i][0].transcript;
        }
      }
      setTranscript(interim);
    };

    recognition.onerror = (event) => {
      console.error('Speech recognition error:', event.error);
      setListening(false);
    };

    recognition.onend = () => {
      setListening(false);
      setTranscript('');
    };

    recognitionRef.current = recognition;
    recognition.start();
    setListening(true);
  };

  const stopListening = () => {
    if (recognitionRef.current) {
      recognitionRef.current.stop();
    }
    const finalText = baseInput + (baseInput && transcript ? ' ' : '') + transcript;
    setListening(false);
    setInput(finalText);
    setBaseInput('');
    setTranscript('');
  };

  if (authLoading || !agent) return (
    <div className="min-h-screen flex flex-col items-center justify-center bg-gray-50">
      <Loader2 className="w-12 h-12 text-blue-600 animate-spin mb-4" />
      <p className="text-gray-600 font-medium">{t('chat:loading.text')}</p>
    </div>
  );

  return (
    <div className="min-h-screen flex flex-row bg-gray-50">
      {/* Colonne gauche : liste des conversations - Version améliorée */}
      <div className="w-80 min-w-[18rem] max-w-xs flex flex-col border-r border-gray-200 bg-white shadow-subtle">
        {/* Header avec profil agent */}
        <div className="p-6 border-b border-gray-200 bg-gradient-to-br from-blue-600 via-purple-600 to-blue-600 relative overflow-hidden">
          {/* Subtle overlay */}
          <div className="absolute inset-0 bg-black/10"></div>

          <div className="relative z-10 flex flex-col items-center">
            {agent.profile_photo && (
              <div className="w-20 h-20 rounded-2xl overflow-hidden border-2 border-white/30 shadow-elevated mb-3 ring-2 ring-white/20">
                <img
                  src={agent.profile_photo.startsWith('http') ? agent.profile_photo : `${process.env.NEXT_PUBLIC_API_URL}/profile_photos/${agent.profile_photo.replace(/^.*[\\/]/, '')}`}
                  alt={agent.name}
                  width={80}
                  height={80}
                  style={{ objectFit: "cover" }}
                  className="w-full h-full"
                  onError={e => { e.target.onerror = null; e.target.src = '/default-avatar.png'; }}
                />
              </div>
            )}
            <h1 className="text-lg font-bold text-white text-center tracking-wide">{agent.name}</h1>
            <div className="flex items-center mt-1">
              <span className="w-2 h-2 rounded-full bg-green-400 animate-pulse mr-2"></span>
              <span className="text-xs text-white/80 capitalize">{agent.type || t('chat:sidebar.agentTypeLabel')}</span>
            </div>
          </div>
        </div>

        {/* Bouton Nouvelle conversation */}
        <div className="p-4 border-b border-gray-200">
          <button
            className="w-full group flex items-center justify-center gap-2 bg-gradient-to-r from-blue-600 to-purple-600 hover:from-blue-500 hover:to-purple-500 text-white py-3 rounded-button font-semibold shadow-card hover:shadow-elevated transition-all disabled:opacity-50 disabled:cursor-not-allowed"
            onClick={handleNewConversation}
            disabled={creatingConv}
          >
            {creatingConv ? (
              <Loader2 className="w-5 h-5 animate-spin" />
            ) : (
              <Plus className="w-5 h-5 group-hover:rotate-90 transition-transform duration-300" />
            )}
            <span>{t('chat:sidebar.newConversationButton')}</span>
          </button>
        </div>

        {/* Liste des conversations */}
        <div className="flex-1 overflow-y-auto p-4 space-y-2">{conversations.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-12 text-center">
              <MessageCircle className="w-12 h-12 text-gray-300 mb-3" />
              <p className="text-sm text-gray-500">{t('chat:sidebar.noConversations')}</p>
              <p className="text-xs text-gray-400 mt-1">{t('chat:sidebar.noConversationsSubtext')}</p>
            </div>
          ) : (
            conversations.map((conv) => (
              <div
                key={conv.id}
                className={`group relative p-4 rounded-button border transition-all duration-200 cursor-pointer ${
                  selectedConv === conv.id
                    ? 'border-blue-400 bg-blue-50 shadow-subtle'
                    : 'border-gray-200 bg-white hover:border-gray-300 hover:shadow-subtle'
                }`}
                onClick={e => { if (e.target === e.currentTarget || e.target.closest('.conv-content')) selectConversation(conv.id); }}
              >
                <div className="flex items-start space-x-3">
                  {/* Icône de conversation */}
                  <div className={`p-2 rounded-lg flex-shrink-0 ${
                    selectedConv === conv.id
                      ? 'bg-blue-100'
                      : 'bg-gray-100 group-hover:bg-gray-200'
                  }`}>
                    <MessageCircle className={`w-4 h-4 ${
                      selectedConv === conv.id ? 'text-blue-600' : 'text-gray-600'
                    }`} />
                  </div>

                  {/* Contenu */}
                  <div className="flex-1 min-w-0 conv-content" onClick={() => selectConversation(conv.id)}>
                    {editingTitleId === conv.id ? (
                      <input
                        className="w-full px-2 py-1 border border-blue-300 rounded-lg text-sm font-medium focus:ring-2 focus:ring-blue-500 focus:border-transparent"
                        value={editedTitle}
                        onChange={e => setEditedTitle(e.target.value)}
                        onBlur={() => handleEditTitle(conv.id)}
                        onKeyDown={e => { if (e.key === "Enter") handleEditTitle(conv.id); }}
                        autoFocus
                        onClick={e => e.stopPropagation()}
                      />
                    ) : (
                      <p className={`text-sm font-semibold truncate ${
                        selectedConv === conv.id ? 'text-blue-700' : 'text-gray-800'
                      }`}>
                        {conv.title || `${t('chat:sidebar.conversationNumber')} ${conversations.findIndex(c => c.id === conv.id) + 1}`}
                      </p>
                    )}
                    <div className="flex items-center mt-1">
                      <span className="w-1 h-1 rounded-full bg-gray-400 mr-1.5"></span>
                      <span className="text-xs text-gray-500">
                        {new Date(conv.created_at).toLocaleDateString('fr-FR', {
                          day: 'numeric',
                          month: 'short'
                        })}
                      </span>
                    </div>
                  </div>

                  {/* Actions */}
                  <div className="flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
                    <button
                      className="p-1.5 rounded-lg text-gray-400 hover:text-blue-600 hover:bg-blue-100 transition-all"
                      title={t('chat:sidebar.renameTooltip')}
                      onClick={e => { e.stopPropagation(); setEditingTitleId(conv.id); setEditedTitle(conv.title || ""); }}
                    >
                      <Pencil className="w-4 h-4" />
                    </button>
                    <button
                      className="p-1.5 rounded-lg text-gray-400 hover:text-red-600 hover:bg-red-100 transition-all"
                      title={t('chat:sidebar.deleteTooltip')}
                      onClick={e => { e.stopPropagation(); handleDeleteConversation(conv.id); }}
                    >
                      <Trash2 className="w-4 h-4" />
                    </button>
                  </div>
                </div>
              </div>
            ))
          )}
        </div>
      </div>

      {/* Colonne droite : chat - Version améliorée */}
      <div className="flex-1 flex flex-col h-screen">
        {/* Header - Version Desktop & Mobile */}
        <div className="flex items-center justify-between px-6 py-4 bg-white shadow-subtle border-b border-gray-200">
          <div className="flex items-center space-x-3">
            <Link href="/agents">
              <button className="group flex items-center space-x-2 text-gray-700 hover:text-blue-600 transition-colors">
                <ArrowLeft className="w-5 h-5 group-hover:-translate-x-1 transition-transform" />
                <span className="hidden md:inline font-medium">{t('chat:header.backButton')}</span>
              </button>
            </Link>
            <div className="h-6 w-px bg-gray-300 hidden md:block"></div>
            <div className="flex items-center space-x-3">
              <div className="p-2 rounded-xl bg-gradient-to-br from-blue-100 to-purple-100">
                <Bot className="w-5 h-5 text-blue-600" />
              </div>
              <div>
                <h2 className="text-lg font-bold text-gray-900">{agent.name}</h2>
                <p className="text-xs text-gray-500 capitalize">{agent.type || t('chat:header.agentTypeDefault')}</p>
              </div>
            </div>
          </div>

          <div className="flex items-center gap-3">
            {/* Bouton retour vers page sources */}
            <Link href={`/sources/${agentId}`}>
              <button className="group flex items-center space-x-2 px-4 py-2 bg-gradient-to-r from-blue-600 to-purple-600 hover:from-blue-500 hover:to-purple-500 text-white rounded-button font-medium shadow-card hover:shadow-elevated transition-all">
                <FileText className="w-4 h-4" />
                <span className="hidden md:inline">{t('chat:header.sourcesButton')}</span>
              </button>
            </Link>
          </div>
        </div>

        {/* Chat area - Version améliorée */}
        <div className="flex-1 overflow-y-auto px-4 md:px-8 py-6 flex flex-col space-y-4">{selectedConv ? (
            <>
          {messages.map((msg, idx) => {
            const isLastAgentMsg =
              msg.role === "agent" &&
              idx === messages.length - 1 &&
              !msg.feedback;

            // Render system action results as clickable previews when they contain a URL
            const extractUrl = (text) => {
              if (!text) return null;
              const m = text.match(/https?:\/\/[^\s)\]\[]+/i);
              return m ? m[0] : null;
            };

            const url = msg.role === "system" ? extractUrl(msg.content) : null;

            return (
              <div key={idx} className={`flex ${msg.role === "user" ? "justify-end" : "justify-start"} animate-fade-in`}>
                <div className={`rounded-2xl px-5 py-3.5 shadow-subtle max-w-[70%] whitespace-pre-line transition-all duration-200 ${
                  msg.role === "user"
                    ? "bg-gradient-to-br from-blue-600 to-blue-700 text-white rounded-br-none"
                    : msg.role === "system"
                      ? "bg-gray-100 text-gray-700 rounded-bl-none border border-gray-200"
                      : "bg-white text-gray-900 rounded-bl-none border border-gray-200"
                }`}>
                  {msg.role === "system" && url ? (
                    <div className="flex flex-col gap-3">
                      <div className="flex items-center space-x-2">
                        <Zap className="w-4 h-4 text-blue-600" />
                        <span className="text-sm font-semibold text-gray-700">{t('chat:messages.actionResult')}</span>
                      </div>
                      <div className="p-4 bg-white border border-blue-200 rounded-button flex flex-col gap-3">
                        <div className="text-sm text-blue-700 break-words">
                          <a href={url} target="_blank" rel="noreferrer" className="hover:underline font-medium">{url}</a>
                        </div>
                        <div className="flex gap-2">
                          <button
                            className="flex items-center space-x-1 px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 transition-all font-medium text-sm"
                            onClick={() => window.open(url, "_blank")}
                          >
                            <ExternalLink className="w-4 h-4" />
                            <span>{t('chat:messages.openButton')}</span>
                          </button>
                          <button
                            className="flex items-center space-x-1 px-4 py-2 bg-gray-200 text-gray-800 rounded-lg hover:bg-gray-300 transition-all font-medium text-sm"
                            onClick={() => { navigator.clipboard?.writeText(url); }}
                          >
                            <Copy className="w-4 h-4" />
                            <span>{t('chat:messages.copyButton')}</span>
                          </button>
                        </div>
                      </div>
                      {msg.content && msg.content.replace(url, '').trim() && (
                        <div className="text-xs text-gray-500 whitespace-pre-line italic">{msg.content.replace(url, '').trim()}</div>
                      )}
                    </div>
                  ) : (
                    // Default rendering for user/agent/system messages without URL
                    <>
                      {msg.role === "agent" ? (
                        <MarkdownText>{msg.content}</MarkdownText>
                      ) : (
                        <div className="leading-relaxed whitespace-pre-line">{msg.content}</div>
                      )}
                      {/* Bouton de feedback uniquement sur le dernier message agent sans feedback */}
                      {isLastAgentMsg && (
                        <div className="flex gap-2 mt-3 pt-3 border-t border-gray-200">
                          <button
                            className="group flex items-center justify-center space-x-1 px-3 py-1.5 bg-gray-100 hover:bg-green-100 text-gray-600 hover:text-green-600 rounded-lg transition-all border border-gray-300 hover:border-green-400"
                            title={t('chat:messages.usefulButton')}
                            onClick={async () => {
                              // Optimistic update: retire le bouton localement
                              setMessages(prevMsgs => prevMsgs.map((m, i) => i === idx ? { ...m, feedback: 'like' } : m));
                              try {
                                await api.patch(`/messages/${msg.id}/feedback`, { feedback: 'like' });
                              } catch {}
                            }}
                          >
                            <ThumbsUp className="w-4 h-4" />
                            <span className="text-sm font-medium">{t('chat:messages.usefulButton')}</span>
                          </button>
                        </div>
                      )}
                    </>
                  )}
                </div>
              </div>
            );
          })}

          {/* Indicateur de typing amélioré */}
          {loading && ((messages.length > 0 && messages[messages.length-1].role === "user") || (messages.length === 1 && messages[0].role === "user")) && (
            <div className="flex justify-start animate-fade-in">
              <div className="rounded-2xl px-5 py-4 shadow-subtle max-w-[70%] bg-white text-gray-900 rounded-bl-none border border-gray-200 flex items-center gap-3">
                <div className="p-2 rounded-lg bg-blue-100">
                  <Loader2 className="w-4 h-4 text-blue-600 animate-spin" />
                </div>
                <div className="flex flex-col">
                  <span className="text-sm font-medium text-gray-700">{t('chat:messages.thinking', { agentName: agent.name })}</span>
                  <div className="flex items-center mt-1">
                    <span className="inline-block w-2 h-2 bg-blue-400 rounded-full animate-bounce mr-1" style={{animationDelay: '0ms'}}></span>
                    <span className="inline-block w-2 h-2 bg-blue-400 rounded-full animate-bounce mr-1" style={{animationDelay: '150ms'}}></span>
                    <span className="inline-block w-2 h-2 bg-blue-400 rounded-full animate-bounce" style={{animationDelay: '300ms'}}></span>
                  </div>
                </div>
              </div>
            </div>
          )}

          <div ref={chatEndRef} />
          </>
          ) : (
            /* Message si aucune conversation sélectionnée */
            <div className="flex-1 flex flex-col items-center justify-center text-center px-4">
              <div className="p-6 rounded-2xl bg-gradient-to-br from-blue-100 to-purple-100 mb-4">
                <MessageCircle className="w-16 h-16 text-blue-600" />
              </div>
              <h3 className="text-xl font-bold text-gray-800 mb-2">{t('chat:emptyState.title')}</h3>
              <p className="text-gray-600 mb-4">{t('chat:emptyState.description', { agentName: agent.name })}</p>
              <button
                className="flex items-center space-x-2 px-6 py-3 bg-gradient-to-r from-blue-600 to-purple-600 hover:from-blue-500 hover:to-purple-500 text-white rounded-button font-semibold shadow-card hover:shadow-elevated transition-all"
                onClick={handleNewConversation}
                disabled={creatingConv}
              >
                {creatingConv ? (
                  <Loader2 className="w-5 h-5 animate-spin" />
                ) : (
                  <Plus className="w-5 h-5" />
                )}
                <span>{t('chat:emptyState.newConversationButton')}</span>
              </button>
            </div>
          )}
        </div>

        {/* Input Area - Version améliorée */}
        <div className="bg-white border-t border-gray-200 p-4 shadow-subtle">
          <div className="max-w-5xl mx-auto">
            {/* Affichage des pièces jointes */}
            {attachments.length > 0 && (
              <div className="mb-3 flex flex-wrap gap-2">
                {attachments.map((file, idx) => (
                  <div key={idx} className="flex items-center space-x-2 px-3 py-2 bg-blue-50 border border-blue-200 rounded-lg">
                    <FileText className="w-4 h-4 text-blue-600" />
                    <span className="text-sm text-gray-700 truncate max-w-[200px]">{file.name}</span>
                    <button
                      onClick={() => setAttachments(attachments.filter((_, i) => i !== idx))}
                      className="text-gray-400 hover:text-red-600 transition-colors"
                    >
                      ×
                    </button>
                  </div>
                ))}
              </div>
            )}

            <div className="flex items-end w-full gap-2">
              {/* Zone de texte */}
              <div className="flex-1 relative">
                <input
                  type="text"
                  className="w-full px-4 py-3 pr-12 border border-gray-200 rounded-input focus:ring-2 focus:ring-blue-500 focus:border-blue-500 transition-all disabled:opacity-50 disabled:bg-gray-50"
                  placeholder={selectedConv ? t('chat:input.placeholder') : t('chat:input.placeholderNoConversation')}
                  value={input}
                  onChange={e => setInput(e.target.value)}
                  onKeyDown={e => e.key === "Enter" && !e.shiftKey && sendMessage()}
                  disabled={loading || !selectedConv}
                />
                {listening && (
                  <div className="absolute right-3 top-1/2 transform -translate-y-1/2 flex items-center space-x-1">
                    <span className="w-2 h-2 bg-red-500 rounded-full animate-pulse"></span>
                    <span className="text-xs text-red-500 font-medium">{t('chat:input.listeningLabel')}</span>
                  </div>
                )}
              </div>

              {/* Boutons d'action */}
              <div className="flex items-center gap-2">
                {/* Bouton pièce jointe */}
                <label className="group p-3 flex items-center justify-center rounded-button border border-gray-200 bg-white hover:bg-gray-50 hover:border-blue-400 text-gray-600 hover:text-blue-600 cursor-pointer transition-all disabled:opacity-50" title={t('chat:input.attachmentTooltip')}>
                  <Paperclip className="w-5 h-5 group-hover:rotate-12 transition-transform" />
                  <input
                    type="file"
                    multiple
                    style={{ display: "none" }}
                    onChange={e => {
                      if (e.target.files) {
                        setAttachments(Array.from(e.target.files));
                      }
                    }}
                    accept=".pdf,.txt,.doc,.docx,.xls,.xlsx,.csv,.ppt,.pptx,.odt,.ods,.odp,.rtf,.html,.md,.json,.xml,image/*"
                    disabled={loading}
                  />
                </label>

                {/* Bouton micro */}
                <button
                  title={listening ? t('chat:input.stopDictationTooltip') : t('chat:input.startDictationTooltip')}
                  onClick={() => listening ? stopListening() : startListening()}
                  aria-pressed={listening}
                  className={`p-3 flex items-center justify-center rounded-button border transition-all ${
                    listening
                      ? 'bg-red-500 border-red-500 text-white ring-4 ring-red-200 animate-pulse'
                      : 'border-gray-200 bg-white hover:bg-gray-50 hover:border-blue-400 text-gray-600 hover:text-blue-600'
                  } focus:outline-none disabled:opacity-50`}
                  disabled={!selectedConv}
                >
                  <Mic className="w-5 h-5" />
                </button>

                {/* Bouton envoyer */}
                <button
                  onClick={sendMessage}
                  className="group px-6 py-3 flex items-center space-x-2 bg-gradient-to-r from-blue-600 to-purple-600 hover:from-blue-500 hover:to-purple-500 text-white rounded-button font-semibold shadow-card hover:shadow-elevated transition-all disabled:opacity-50 disabled:cursor-not-allowed"
                  disabled={loading || (!input.trim() && attachments.length === 0) || !selectedConv}
                >
                  {uploadingAttachments ? (
                    <>
                      <Loader2 className="w-5 h-5 animate-spin" />
                      <span className="hidden md:inline">{t('chat:input.extractingButton')}</span>
                    </>
                  ) : loading ? (
                    <>
                      <Loader2 className="w-5 h-5 animate-spin" />
                      <span className="hidden md:inline">{t('chat:input.sendingButton')}</span>
                    </>
                  ) : (
                    <>
                      <Send className="w-5 h-5 group-hover:translate-x-1 transition-transform" />
                      <span className="hidden md:inline">{t('chat:input.sendButton')}</span>
                    </>
                  )}
                </button>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

export async function getServerSideProps({ locale }) {
  // Auth check is handled client-side via useAuth hook
  return {
    props: {
      ...(await serverSideTranslations(locale, ['chat', 'common', 'errors'])),
    },
  };
}
