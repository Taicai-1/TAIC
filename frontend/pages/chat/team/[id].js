import { useState, useEffect, useRef } from "react";
import { useRouter } from "next/router";
import Link from "next/link";
import { Pencil, Trash2, Plus, Users, ArrowLeft, Send, ThumbsUp, MessageCircle, Sparkles, Bot } from "lucide-react";
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import toast, { Toaster } from "react-hot-toast";
import { useTranslation } from 'next-i18next';
import { serverSideTranslations } from 'next-i18next/serverSideTranslations';
import { useAuth } from '../../../hooks/useAuth';
import api from '../../../lib/api';

export default function TeamChatPage() {
  const { t } = useTranslation(['chat', 'teams', 'common', 'errors']);
  const router = useRouter();
  const { id: teamId } = router.query;
  const { user, loading: authLoading, authenticated } = useAuth();
  const [team, setTeam] = useState(null);
  const [conversations, setConversations] = useState([]);
  const [selectedConv, setSelectedConv] = useState(null);
  const [messages, setMessages] = useState([]);
  const [pendingUserMessage, setPendingUserMessage] = useState(null);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const chatEndRef = useRef(null);
  const [creatingConv, setCreatingConv] = useState(false);
  const [editingTitleId, setEditingTitleId] = useState(null);
  const [editedTitle, setEditedTitle] = useState("");

  useEffect(() => {
    if (authLoading) return;
    if (!authenticated) {
      router.push("/login");
      return;
    }
    if (teamId) {
      loadTeam(teamId);
      loadConversations(teamId, true);
    }
  }, [teamId, authenticated, authLoading]);

  const loadTeam = async (id) => {
    try {
      const res = await api.get(`/teams/${id}`);
      setTeam(res.data);
    } catch (e) {
      toast.error(t('teams:chat.loadingError'));
      router.push("/teams");
    }
  };

  const loadConversations = async (teamId, autoCreateIfNone = false) => {
    try {
      const res = await api.get(`/conversations?team_id=${teamId}`);
      setConversations(res.data);
      if (res.data.length > 0) {
        selectConversation(res.data[0].id);
      } else if (autoCreateIfNone) {
        await handleNewConversation(true);
      }
    } catch (e) {
      setConversations([]);
    }
  };

  const selectConversation = async (convId) => {
    setSelectedConv(convId);
    if (!pendingUserMessage) setMessages([]);
    try {
      const res = await api.get(`/conversations/${convId}/messages`);
      if (pendingUserMessage && res.data.length === 0) {
        setMessages([pendingUserMessage]);
      } else {
        setMessages(res.data);
      }
      setPendingUserMessage(null);
    } catch (e) {
      if (pendingUserMessage) {
        setMessages([pendingUserMessage]);
        setPendingUserMessage(null);
      } else {
        setMessages([]);
      }
    }
  };

  const handleNewConversation = async (auto = false) => {
    setCreatingConv(true);
    const convCount = conversations.length + 1;
    const convTitle = `${t('chat:sidebar.conversationNumber')} ${convCount}`;
    try {
      const res = await api.post(`/conversations`, {
        team_id: teamId,
        title: convTitle
      });
      setCreatingConv(false);
      await loadConversations(teamId);
      if (res.data.conversation_id) {
        setSelectedConv(res.data.conversation_id);
        setMessages([]);
      }
      toast.success(t('teams:chat.conversationCreated'));
    } catch (e) {
      setCreatingConv(false);
      toast.error(t('teams:chat.createError'));
    }
  };

  const handleEditTitle = async (convId) => {
    try {
      await api.put(`/conversations/${convId}/title`, { title: editedTitle });
      await loadConversations(teamId);
      setEditingTitleId(null);
      toast.success(t('teams:chat.titleUpdated'));
    } catch (e) {
      toast.error(t('teams:chat.updateError'));
    }
  };

  const handleDeleteConversation = async (convId) => {
    if (!confirm(t('chat:sidebar.deleteConfirmation'))) return;
    try {
      await api.delete(`/conversations/${convId}`);
      await loadConversations(teamId);
      if (selectedConv === convId) {
        setSelectedConv(null);
        setMessages([]);
      }
      toast.success(t('teams:chat.conversationDeleted'));
    } catch (e) {
      toast.error(t('teams:chat.deleteError'));
    }
  };

  const sendMessage = async () => {
    if (!input.trim() || !selectedConv) return;
    const userMsg = { role: "user", content: input };
    setMessages(prev => [...prev, userMsg]);
    setPendingUserMessage(userMsg);
    setLoading(true);
    const userMessage = input;
    setInput("");
    try {
      const conv = conversations.find(c => c.id === selectedConv);
      if (conv && (conv.title === `${t('chat:sidebar.conversationNumber')} ${conversations.indexOf(conv)+1}` || !conv.title || conv.title === "")) {
        const firstMsgTitle = userMessage.length > 50 ? userMessage.slice(0, 50) + "..." : userMessage;
        await api.put(`/conversations/${selectedConv}/title`, { title: firstMsgTitle });
        await loadConversations(teamId);
      }
      await api.post(`/conversations/${selectedConv}/messages`, {
        conversation_id: selectedConv,
        role: "user",
        content: userMessage
      });
      const resHist = await api.get(`/conversations/${selectedConv}/messages`);
      const history = resHist.data.map(m => ({ role: m.role, content: m.content }));
      const resAsk = await api.post(`/ask`, {
        question: userMessage,
        team_id: teamId,
        history: history
      });
      const iaAnswer = resAsk.data.answer || t('chat:messages.aiError');
      await api.post(`/conversations/${selectedConv}/messages`, {
        conversation_id: selectedConv,
        role: "agent",
        content: iaAnswer
      });
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
              content = `Action ${ar.action}: ${JSON.stringify(ar.result)}`;
            }
          } else {
            content = `Action ${ar.action}: ${JSON.stringify(ar)}`;
          }
          await api.post(`/conversations/${selectedConv}/messages`, {
            conversation_id: selectedConv,
            role: "system",
            content: content
          });
        } catch (e) {}
      }
      await selectConversation(selectedConv);
    } catch (e) {
      toast.error(t('teams:chat.sendError'));
      setLoading(false);
    } finally {
      setLoading(false);
      setPendingUserMessage(null);
      setTimeout(() => chatEndRef.current?.scrollIntoView({ behavior: "smooth" }), 100);
    }
  };

  useEffect(() => {
    setTimeout(() => chatEndRef.current?.scrollIntoView({ behavior: "smooth" }), 100);
  }, [messages]);

  if (!team) {
    return (
      <div className="min-h-screen bg-gray-50 flex items-center justify-center">
        <div className="flex flex-col items-center">
          <div className="animate-spin rounded-full h-16 w-16 border-b-4 border-blue-600 mb-4"></div>
          <p className="text-gray-600 font-medium">{t('teams:chat.loading')}</p>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen flex flex-col md:flex-row bg-gray-50">

      <Toaster position="top-right" />

      {/* Sidebar: Conversations */}
      <div className="w-full md:w-80 md:min-w-[20rem] md:max-w-xs flex flex-col bg-white border-r border-gray-200 shadow-card">
        {/* Header */}
        <div className="bg-gradient-to-r from-purple-600 via-blue-600 to-purple-600 p-6 shadow-card border-b border-purple-700">
          <div className="flex items-center justify-between mb-4">
            <Link href="/teams">
              <button className="group flex items-center text-white/90 hover:text-white transition-colors">
                <ArrowLeft className="w-5 h-5 mr-2 group-hover:-translate-x-1 transition-transform" />
                <span className="font-medium">{t('teams:chat.backToTeams')}</span>
              </button>
            </Link>
          </div>
          <div className="flex items-center space-x-3">
            <div className="relative">
              <Users className="w-10 h-10 text-yellow-300" />
              <div className="absolute -top-1 -right-1 w-3 h-3 bg-green-400 rounded-full animate-pulse"></div>
            </div>
            <div>
              <h1 className="text-xl font-bold font-heading text-white">{team.name || `${t('common:navigation.teams')} ${teamId}`}</h1>
              <p className="text-blue-100 text-sm">{t('teams:chat.teamChat')}</p>
            </div>
          </div>
        </div>

        {/* New Conversation Button */}
        <div className="p-4 border-b border-gray-200 bg-gray-50">
          <button
            className="group w-full flex items-center justify-center px-6 py-3 bg-gradient-to-r from-blue-600 to-purple-600 text-white rounded-button hover:from-blue-700 hover:to-purple-700 font-semibold shadow-card hover:shadow-elevated transition-all duration-300 disabled:opacity-50 disabled:cursor-not-allowed"
            onClick={handleNewConversation}
            disabled={creatingConv}
          >
            {creatingConv ? (
              <div className="flex items-center">
                <div className="animate-spin rounded-full h-5 w-5 border-b-2 border-white mr-2"></div>
                <span>{t('teams:chat.creatingConversation')}</span>
              </div>
            ) : (
              <div className="flex items-center">
                <Plus className="w-5 h-5 mr-2 group-hover:rotate-90 transition-transform duration-300" />
                <span>{t('teams:chat.newConversation')}</span>
                <Sparkles className="w-4 h-4 ml-2 group-hover:rotate-12 transition-transform" />
              </div>
            )}
          </button>
        </div>

        {/* Conversations List */}
        <div className="flex-1 overflow-y-auto p-4 space-y-3">
          {conversations.length === 0 ? (
            <div className="text-center py-12">
              <MessageCircle className="w-16 h-16 mx-auto text-gray-300 mb-4" />
              <p className="text-gray-500 text-sm">{t('chat:sidebar.noConversations')}</p>
            </div>
          ) : (
            conversations.map((conv) => (
              <div
                key={conv.id}
                className={`group relative flex items-center p-4 rounded-card shadow-subtle transition-all duration-300 cursor-pointer ${
                  selectedConv === conv.id
                    ? 'bg-gradient-to-r from-blue-600 to-purple-600 text-white shadow-card'
                    : 'bg-white hover:bg-gray-50 hover:shadow-card'
                }`}
                onClick={(e) => {
                  if (e.target === e.currentTarget || e.target.closest('.conv-title')) {
                    selectConversation(conv.id);
                  }
                }}
              >
                <div className="flex-1 min-w-0 conv-title" onClick={() => selectConversation(conv.id)}>
                  {editingTitleId === conv.id ? (
                    <input
                      className="w-full px-3 py-2 border border-blue-300 rounded-input focus:border-blue-500 focus:ring-2 focus:ring-blue-200 transition-all outline-none bg-white text-gray-900"
                      value={editedTitle}
                      onChange={(e) => setEditedTitle(e.target.value)}
                      onBlur={() => handleEditTitle(conv.id)}
                      onKeyDown={(e) => {
                        if (e.key === "Enter") handleEditTitle(conv.id);
                      }}
                      autoFocus
                      onClick={(e) => e.stopPropagation()}
                    />
                  ) : (
                    <>
                      <div className={`font-semibold truncate mb-1 ${selectedConv === conv.id ? 'text-white' : 'text-gray-900'}`}>
                        {conv.title || `${t('chat:sidebar.conversationNumber')} ${conversations.findIndex((c) => c.id === conv.id) + 1}`}
                      </div>
                      <div className={`text-xs ${selectedConv === conv.id ? 'text-blue-100' : 'text-gray-500'}`}>
                        {new Date(conv.created_at).toLocaleDateString(router.locale || 'fr-FR', { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' })}
                      </div>
                    </>
                  )}
                </div>
                <div className={`flex items-center ml-2 gap-1 ${selectedConv === conv.id ? 'opacity-100' : 'opacity-0 group-hover:opacity-100'} transition-opacity`}>
                  <button
                    className={`p-2 rounded-lg transition-all ${
                      selectedConv === conv.id
                        ? 'bg-white/20 hover:bg-white/30 text-white'
                        : 'bg-blue-50 hover:bg-blue-100 text-blue-600'
                    }`}
                    title={t('chat:sidebar.renameTooltip')}
                    onClick={(e) => {
                      e.stopPropagation();
                      setEditingTitleId(conv.id);
                      setEditedTitle(conv.title || "");
                    }}
                  >
                    <Pencil className="w-4 h-4" />
                  </button>
                  <button
                    className={`p-2 rounded-lg transition-all ${
                      selectedConv === conv.id
                        ? 'bg-white/20 hover:bg-red-500 text-white'
                        : 'bg-red-50 hover:bg-red-100 text-red-600'
                    }`}
                    title={t('chat:sidebar.deleteTooltip')}
                    onClick={(e) => {
                      e.stopPropagation();
                      handleDeleteConversation(conv.id);
                    }}
                  >
                    <Trash2 className="w-4 h-4" />
                  </button>
                </div>
              </div>
            ))
          )}
        </div>
      </div>

      {/* Main Chat Area */}
      <div className="flex-1 flex flex-col h-screen">
        {/* Chat Messages */}
        <div className="flex-1 overflow-y-auto px-4 md:px-8 py-8 space-y-6">
          {messages.length === 0 && !loading ? (
            <div className="flex flex-col items-center justify-center h-full text-center">
              <div className="relative mb-6">
                <Bot className="w-24 h-24 text-blue-300" />
                <div className="absolute -top-2 -right-2 w-8 h-8 bg-gradient-to-r from-blue-500 to-purple-500 rounded-full flex items-center justify-center animate-bounce">
                  <Sparkles className="w-5 h-5 text-white" />
                </div>
              </div>
              <h3 className="text-2xl font-bold font-heading bg-gradient-to-r from-blue-600 to-purple-600 bg-clip-text text-transparent mb-2">
                {t('teams:chat.startConversation')}
              </h3>
              <p className="text-gray-500">{t('teams:chat.sendMessageToStart')}</p>
            </div>
          ) : (
            messages.map((msg, idx) => {
              const isLastAgentMsg =
                msg.role === "agent" &&
                idx === messages.length - 1 &&
                !msg.feedback;
              return (
                <div
                  key={idx}
                  className={`flex ${msg.role === "user" ? "justify-end" : "justify-start"} animate-fade-in`}
                >
                  <div
                    className={`rounded-2xl px-5 py-4 max-w-[75%] transition-all duration-300 ${
                      msg.role === "user"
                        ? "bg-gradient-to-r from-blue-600 to-purple-600 text-white rounded-br-none shadow-card"
                        : "bg-white text-gray-900 rounded-bl-none border border-gray-100 shadow-subtle"
                    }`}
                  >
                    <div className="prose prose-sm max-w-none">
                      <ReactMarkdown
                        remarkPlugins={[remarkGfm]}
                        components={{
                          p: ({ node, ...props }) => <p className={msg.role === "user" ? "text-white mb-2 last:mb-0" : "text-gray-900 mb-2 last:mb-0"} {...props} />,
                          strong: ({ node, ...props }) => <strong className={msg.role === "user" ? "text-white font-bold" : "text-gray-900 font-bold"} {...props} />,
                          em: ({ node, ...props }) => <em className={msg.role === "user" ? "text-white italic" : "text-gray-700 italic"} {...props} />,
                          ul: ({ node, ...props }) => <ul className={`${msg.role === "user" ? "text-white" : "text-gray-900"} list-disc ml-4 mb-2`} {...props} />,
                          ol: ({ node, ...props }) => <ol className={`${msg.role === "user" ? "text-white" : "text-gray-900"} list-decimal ml-4 mb-2`} {...props} />,
                          li: ({ node, ...props }) => <li className="mb-1" {...props} />,
                          code: ({ node, inline, ...props }) =>
                            inline ? (
                              <code className={`${msg.role === "user" ? "bg-white/20 text-white" : "bg-gray-100 text-gray-900"} px-1.5 py-0.5 rounded text-sm`} {...props} />
                            ) : (
                              <code className={`block ${msg.role === "user" ? "bg-white/20 text-white" : "bg-gray-100 text-gray-900"} p-3 rounded-lg text-sm overflow-x-auto`} {...props} />
                            ),
                          a: ({ node, ...props }) => <a className={msg.role === "user" ? "text-blue-200 underline hover:text-blue-100" : "text-blue-600 underline hover:text-blue-800"} target="_blank" rel="noopener noreferrer" {...props} />,
                          table: ({ node, ...props }) => (
                            <div className="overflow-x-auto my-3">
                              <table className="min-w-full border-collapse border border-gray-200 rounded-lg text-sm" {...props} />
                            </div>
                          ),
                          thead: ({ node, ...props }) => <thead className="bg-gray-50" {...props} />,
                          th: ({ node, ...props }) => <th className="border border-gray-200 px-3 py-2 text-left font-semibold text-gray-700" {...props} />,
                          td: ({ node, ...props }) => <td className="border border-gray-200 px-3 py-2 text-gray-700" {...props} />,
                        }}
                      >
                        {msg.content}
                      </ReactMarkdown>
                    </div>
                    {isLastAgentMsg && (
                      <div className="flex gap-2 mt-3 pt-3 border-t border-gray-200">
                        <button
                          className="group flex items-center px-3 py-2 bg-gray-100 hover:bg-green-100 text-gray-700 hover:text-green-700 rounded-button transition-all duration-300 border border-gray-200 hover:border-green-300"
                          title={t('chat:messages.usefulButton')}
                          onClick={async () => {
                            setMessages((prevMsgs) =>
                              prevMsgs.map((m, i) => (i === idx ? { ...m, feedback: "like" } : m))
                            );
                            try {
                              await api.patch(
                                `/messages/${msg.id}/feedback`,
                                { feedback: "like" }
                              );
                              toast.success(t('teams:chat.feedbackThanks'));
                            } catch {}
                          }}
                        >
                          <ThumbsUp className="w-4 h-4 mr-2 group-hover:scale-110 transition-transform" />
                          <span className="text-sm font-medium">{t('chat:messages.usefulButton')}</span>
                        </button>
                      </div>
                    )}
                  </div>
                </div>
              );
            })
          )}
          {loading && ((messages.length > 0 && messages[messages.length - 1].role === "user") || (messages.length === 1 && messages[0].role === "user")) && (
            <div className="flex justify-start animate-fade-in">
              <div className="rounded-2xl px-5 py-4 shadow-subtle max-w-[75%] bg-white text-gray-900 rounded-bl-none border border-gray-100 flex items-center gap-3">
                <Bot className="w-6 h-6 text-blue-600 animate-pulse" />
                <span className="italic text-gray-500 mr-2">{t('teams:chat.teamThinking')}</span>
                <span className="inline-block w-2 h-2 bg-blue-400 rounded-full animate-bounce" style={{ animationDelay: "0ms" }}></span>
                <span className="inline-block w-2 h-2 bg-purple-400 rounded-full animate-bounce" style={{ animationDelay: "150ms" }}></span>
                <span className="inline-block w-2 h-2 bg-pink-400 rounded-full animate-bounce" style={{ animationDelay: "300ms" }}></span>
              </div>
            </div>
          )}
          <div ref={chatEndRef} />
        </div>

        {/* Input Area */}
        <div className="bg-white border-t border-gray-200 p-4 md:p-6 shadow-card">
          <div className="flex items-center gap-3 max-w-5xl mx-auto">
            <input
              type="text"
              className="flex-1 px-5 py-4 border border-gray-200 rounded-input focus:ring-2 focus:ring-blue-500 focus:border-blue-500 transition-all outline-none bg-white placeholder-gray-400 disabled:bg-gray-100 disabled:cursor-not-allowed"
              placeholder={selectedConv ? t('chat:input.placeholder') : t('chat:input.placeholderNoConversation')}
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && !loading && sendMessage()}
              disabled={loading || !selectedConv}
            />
            <button
              onClick={sendMessage}
              className="group flex items-center px-6 py-4 bg-gradient-to-r from-blue-600 to-purple-600 text-white rounded-button font-semibold hover:from-blue-700 hover:to-purple-700 transition-all duration-300 disabled:opacity-50 disabled:cursor-not-allowed shadow-card hover:shadow-elevated"
              disabled={loading || !input.trim() || !selectedConv}
            >
              <Send className="w-5 h-5 mr-2 group-hover:translate-x-1 transition-transform" />
              <span>{t('chat:input.sendButton')}</span>
            </button>
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
      ...(await serverSideTranslations(locale, ['chat', 'teams', 'common', 'errors'])),
    },
  };
}
