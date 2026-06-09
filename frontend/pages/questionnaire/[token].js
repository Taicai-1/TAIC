import { useState, useEffect, useRef } from 'react';
import { useRouter } from 'next/router';
import { useTranslation } from 'next-i18next';
import { serverSideTranslations } from 'next-i18next/serverSideTranslations';
import { Bot, Send, Star, CheckCircle } from 'lucide-react';
import axios from 'axios';

const API_URL = '/_api';

export default function PublicQuestionnaire() {
  const { t } = useTranslation('questionnaire');
  const router = useRouter();
  const { token } = router.query;
  const messagesEndRef = useRef(null);

  const [questionnaire, setQuestionnaire] = useState(null);
  const [messages, setMessages] = useState([]);
  const [currentQuestionIndex, setCurrentQuestionIndex] = useState(0);
  const [inputValue, setInputValue] = useState('');
  const [selectedChoices, setSelectedChoices] = useState([]);
  const [selectedRating, setSelectedRating] = useState(0);
  const [isCompleted, setIsCompleted] = useState(false);
  const [isLoading, setIsLoading] = useState(true);
  const [isSending, setIsSending] = useState(false);
  const [error, setError] = useState(null);

  useEffect(() => {
    if (token) loadQuestionnaire();
  }, [token]);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  const loadQuestionnaire = async () => {
    try {
      const res = await axios.get(`${API_URL}/questionnaire/${token}`);
      if (res.data.status === 'completed') {
        setIsCompleted(true);
        setIsLoading(false);
        return;
      }
      setQuestionnaire(res.data);

      // Filter out already-answered questions
      const answeredIds = new Set(res.data.answered_question_ids || []);
      const unanswered = res.data.questions.filter(q => !answeredIds.has(q.id));

      if (unanswered.length === 0) {
        setIsCompleted(true);
        setIsLoading(false);
        return;
      }

      // Replace questions with only unanswered ones
      res.data.questions = unanswered;
      setQuestionnaire(res.data);

      // Welcome message
      const welcomeMsg = res.data.welcome_message
        ? `Bonjour${res.data.respondent_name ? ` ${res.data.respondent_name}` : ''} ! ${res.data.welcome_message}`
        : `Bonjour${res.data.respondent_name ? ` ${res.data.respondent_name}` : ''} ! Merci de prendre le temps de répondre à ce questionnaire.`;
      setMessages([{ role: 'agent', content: welcomeMsg }]);

      // Show first question after a brief delay
      setTimeout(() => {
        setMessages(prev => [...prev, { role: 'agent', content: unanswered[0].question_text, questionIndex: 0 }]);
        setIsLoading(false);
      }, 800);
    } catch (err) {
      if (err.response?.status === 404) {
        setError(t('public.notFound'));
      } else if (err.response?.data?.status === 'completed') {
        setIsCompleted(true);
      }
      setIsLoading(false);
    }
  };

  const currentQuestion = questionnaire?.questions?.[currentQuestionIndex];

  const submitAnswer = async (answerText) => {
    if (!currentQuestion || isSending) return;
    setIsSending(true);

    // Add user message
    setMessages(prev => [...prev, { role: 'user', content: answerText }]);

    try {
      await axios.post(`${API_URL}/questionnaire/${token}/answer`, {
        question_id: currentQuestion.id,
        answer_text: answerText,
      });

      const nextIndex = currentQuestionIndex + 1;
      if (nextIndex < questionnaire.questions.length) {
        setCurrentQuestionIndex(nextIndex);
        setInputValue('');
        setSelectedChoices([]);
        setSelectedRating(0);
        // Show next question
        setTimeout(() => {
          setMessages(prev => [...prev, {
            role: 'agent',
            content: questionnaire.questions[nextIndex].question_text,
            questionIndex: nextIndex,
          }]);
        }, 500);
      } else {
        // Complete
        try {
          const res = await axios.post(`${API_URL}/questionnaire/${token}/complete`);
          setMessages(prev => [...prev, { role: 'agent', content: res.data.closing_message || 'Merci pour vos réponses !' }]);
        } catch {
          setMessages(prev => [...prev, { role: 'agent', content: 'Merci pour vos réponses !' }]);
        }
        setIsCompleted(true);
      }
    } catch (err) {
      console.error('Failed to submit answer:', err);
    } finally {
      setIsSending(false);
    }
  };

  const handleTextSubmit = () => {
    if (!inputValue.trim()) return;
    submitAnswer(inputValue.trim());
  };

  const handleSingleChoice = (option) => {
    submitAnswer(option);
  };

  const handleMultipleChoiceConfirm = () => {
    if (selectedChoices.length === 0) return;
    submitAnswer(selectedChoices.join(', '));
  };

  const handleRatingSubmit = () => {
    if (selectedRating === 0) return;
    submitAnswer(String(selectedRating));
  };

  const toggleChoice = (option) => {
    setSelectedChoices(prev =>
      prev.includes(option) ? prev.filter(c => c !== option) : [...prev, option]
    );
  };

  // Parse options for current question
  const parsedOptions = (() => {
    if (!currentQuestion?.options) return [];
    try { return JSON.parse(currentQuestion.options); } catch { return []; }
  })();

  const ratingConfig = (() => {
    if (currentQuestion?.question_type !== 'rating') return { min: 1, max: 5 };
    try { return JSON.parse(currentQuestion?.options || '{}'); } catch { return { min: 1, max: 5 }; }
  })();

  if (isLoading) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-gray-50">
        <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-primary-600"></div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-gray-50">
        <p className="text-gray-500">{error}</p>
      </div>
    );
  }

  if (isCompleted && messages.length === 0) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-gray-50">
        <div className="text-center">
          <CheckCircle className="w-16 h-16 text-green-500 mx-auto mb-4" />
          <p className="text-gray-600 text-lg">{t('public.completed')}</p>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-gray-50 flex flex-col">
      {/* Header */}
      <div className="bg-white border-b border-gray-200 px-6 py-4 flex items-center gap-3 shadow-sm">
        <div className="w-10 h-10 rounded-full bg-gradient-to-br from-primary-500 to-purple-500 flex items-center justify-center">
          <Bot className="w-5 h-5 text-white" />
        </div>
        <div>
          <h1 className="font-heading font-bold text-gray-900">{questionnaire?.agent_name || 'Questionnaire'}</h1>
          <p className="text-xs text-gray-500">TAIC Companion</p>
        </div>
      </div>

      {/* Messages */}
      <div className="flex-1 overflow-y-auto px-4 py-6 max-w-2xl mx-auto w-full">
        <div className="space-y-4">
          {messages.map((msg, idx) => (
            <div key={idx} className={`flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'} items-end gap-2 animate-fade-in`}>
              {msg.role === 'agent' && (
                <div className="w-7 h-7 rounded-sm bg-primary-50 flex items-center justify-center shrink-0 mb-1">
                  <Bot className="w-3.5 h-3.5 text-primary-600" />
                </div>
              )}
              <div className={`rounded-2xl px-5 py-3.5 max-w-[75%] shadow-sm ${
                msg.role === 'user'
                  ? 'bg-gradient-to-br from-primary-600 to-primary-700 text-white rounded-br-none'
                  : 'bg-white text-gray-900 rounded-bl-none border border-gray-200'
              }`}>
                <p className="leading-relaxed whitespace-pre-line text-sm">{msg.content}</p>
              </div>
            </div>
          ))}
          <div ref={messagesEndRef} />
        </div>
      </div>

      {/* Input area */}
      {!isCompleted && currentQuestion && (
        <div className="border-t border-gray-200 bg-white px-4 py-4">
          <div className="max-w-2xl mx-auto">
            {/* Open question */}
            {currentQuestion.question_type === 'open' && (
              <div className="flex items-center gap-2">
                <input
                  type="text"
                  value={inputValue}
                  onChange={(e) => setInputValue(e.target.value)}
                  onKeyDown={(e) => e.key === 'Enter' && handleTextSubmit()}
                  placeholder={t('public.inputPlaceholder')}
                  className="flex-1 px-4 py-3 border border-gray-200 rounded-full text-sm focus:ring-2 focus:ring-primary-500 focus:border-primary-500"
                  disabled={isSending}
                />
                <button
                  onClick={handleTextSubmit}
                  disabled={!inputValue.trim() || isSending}
                  className="p-3 bg-primary-600 text-white rounded-full hover:bg-primary-700 disabled:opacity-50 transition-colors"
                >
                  <Send className="w-4 h-4" />
                </button>
              </div>
            )}

            {/* Single choice */}
            {currentQuestion.question_type === 'single_choice' && (
              <div className="flex flex-wrap gap-2 justify-center">
                {parsedOptions.map((opt, idx) => (
                  <button
                    key={idx}
                    onClick={() => handleSingleChoice(opt)}
                    disabled={isSending}
                    className="px-5 py-2.5 border border-gray-200 rounded-full text-sm font-medium text-gray-700 hover:bg-primary-50 hover:border-primary-300 hover:text-primary-700 transition-colors disabled:opacity-50"
                  >
                    {opt}
                  </button>
                ))}
              </div>
            )}

            {/* Multiple choice */}
            {currentQuestion.question_type === 'multiple_choice' && (
              <div className="space-y-3">
                <div className="flex flex-wrap gap-2 justify-center">
                  {parsedOptions.map((opt, idx) => (
                    <button
                      key={idx}
                      onClick={() => toggleChoice(opt)}
                      disabled={isSending}
                      className={`px-5 py-2.5 border rounded-full text-sm font-medium transition-colors ${
                        selectedChoices.includes(opt)
                          ? 'bg-primary-600 text-white border-primary-600'
                          : 'border-gray-200 text-gray-700 hover:bg-primary-50 hover:border-primary-300'
                      }`}
                    >
                      {opt}
                    </button>
                  ))}
                </div>
                <div className="text-center">
                  <button
                    onClick={handleMultipleChoiceConfirm}
                    disabled={selectedChoices.length === 0 || isSending}
                    className="px-6 py-2.5 bg-primary-600 text-white rounded-full text-sm font-medium hover:bg-primary-700 disabled:opacity-50 transition-colors"
                  >
                    {t('public.validateChoices')} ({selectedChoices.length})
                  </button>
                </div>
              </div>
            )}

            {/* Rating */}
            {currentQuestion.question_type === 'rating' && (
              <div className="space-y-3">
                <div className="flex justify-center gap-2">
                  {Array.from({ length: (ratingConfig.max || 5) - (ratingConfig.min || 1) + 1 }, (_, i) => {
                    const value = (ratingConfig.min || 1) + i;
                    return (
                      <button
                        key={value}
                        onClick={() => setSelectedRating(value)}
                        disabled={isSending}
                        className="p-1 transition-transform hover:scale-110"
                      >
                        <Star className={`w-8 h-8 ${value <= selectedRating ? 'text-yellow-400 fill-yellow-400' : 'text-gray-300'}`} />
                      </button>
                    );
                  })}
                </div>
                {selectedRating > 0 && (
                  <div className="text-center">
                    <button
                      onClick={handleRatingSubmit}
                      disabled={isSending}
                      className="px-6 py-2.5 bg-primary-600 text-white rounded-full text-sm font-medium hover:bg-primary-700 disabled:opacity-50 transition-colors"
                    >
                      {t('public.nextButton')}
                    </button>
                  </div>
                )}
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

export async function getServerSideProps({ locale }) {
  return {
    props: {
      ...(await serverSideTranslations(locale, ['questionnaire', 'common'])),
    },
  };
}
