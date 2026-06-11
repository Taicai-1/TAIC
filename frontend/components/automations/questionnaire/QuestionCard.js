import { useState } from 'react';
import { useTranslation } from 'next-i18next';
import { GripVertical, Trash2, ChevronDown, ChevronUp, Plus, X, Star, ToggleLeft, ToggleRight } from 'lucide-react';
import { QUESTION_TYPES } from './constants';

export default function QuestionCard({ question, index, onChange, onDelete, disabled = false }) {
  const { t } = useTranslation('automations');
  const [expanded, setExpanded] = useState(true);

  const parsedOptions = (() => {
    if (!question.options) return [];
    try { return JSON.parse(question.options); } catch { return []; }
  })();

  const ratingConfig = (() => {
    if (question.question_type !== 'rating' || !question.options) return { min: 1, max: 5 };
    try { return JSON.parse(question.options); } catch { return { min: 1, max: 5 }; }
  })();

  const updateField = (field, value) => onChange({ ...question, [field]: value });
  const updateOptions = (opts) => updateField('options', JSON.stringify(opts));
  const updateRatingConfig = (key, value) => {
    const cfg = { ...ratingConfig, [key]: parseInt(value, 10) || 1 };
    updateField('options', JSON.stringify(cfg));
  };

  const addOption = () => updateOptions([...parsedOptions, '']);
  const removeOption = (idx) => updateOptions(parsedOptions.filter((_, i) => i !== idx));
  const setOptionValue = (idx, value) => {
    const next = [...parsedOptions];
    next[idx] = value;
    updateOptions(next);
  };

  const changeType = (newType) => {
    const update = { ...question, question_type: newType };
    if (newType === 'rating') {
      update.options = JSON.stringify({ min: 1, max: 5 });
    } else if (newType === 'open') {
      update.options = null;
    } else if (!Array.isArray(parsedOptions) || !parsedOptions.length) {
      update.options = JSON.stringify(['']);
    }
    onChange(update);
  };

  return (
    <div className="border border-gray-200 rounded-card bg-white shadow-subtle">
      <div className="flex items-center gap-2 px-4 py-3 border-b border-gray-100">
        <GripVertical className="w-4 h-4 text-gray-300" />
        <span className="text-sm font-semibold text-gray-500 w-6">{index + 1}.</span>
        <span className="flex-1 text-sm font-medium text-gray-800 truncate">
          {question.question_text || t('builder.questionPlaceholder')}
        </span>
        <span className="text-xs px-2 py-0.5 rounded-full bg-primary-50 text-primary-700 font-medium">
          {t(`builder.types.${question.question_type}`)}
        </span>
        <button onClick={() => setExpanded(!expanded)} className="p-1 text-gray-400 hover:text-gray-600">
          {expanded ? <ChevronUp className="w-4 h-4" /> : <ChevronDown className="w-4 h-4" />}
        </button>
        {!disabled && (
          <button onClick={onDelete} className="p-1 text-gray-400 hover:text-red-500">
            <Trash2 className="w-4 h-4" />
          </button>
        )}
      </div>

      {expanded && (
        <div className="px-4 py-4 space-y-4">
          <input
            type="text"
            value={question.question_text}
            disabled={disabled}
            onChange={(e) => updateField('question_text', e.target.value)}
            placeholder={t('builder.questionPlaceholder')}
            className="w-full px-3 py-2 border border-gray-200 rounded-input text-sm focus:ring-2 focus:ring-primary-500 focus:border-primary-500 disabled:bg-gray-50"
          />

          <div className="flex items-center gap-3">
            <label className="text-sm text-gray-600 font-medium">{t('builder.questionType')}</label>
            <select
              value={question.question_type}
              disabled={disabled}
              onChange={(e) => changeType(e.target.value)}
              className="px-3 py-1.5 border border-gray-200 rounded-input text-sm bg-white focus:ring-2 focus:ring-primary-500"
            >
              {QUESTION_TYPES.map((qt) => (
                <option key={qt} value={qt}>{t(`builder.types.${qt}`)}</option>
              ))}
            </select>

            <button
              onClick={() => !disabled && updateField('required', !question.required)}
              className="ml-auto flex items-center gap-1.5 text-sm text-gray-600"
            >
              {question.required ? (
                <ToggleRight className="w-5 h-5 text-primary-600" />
              ) : (
                <ToggleLeft className="w-5 h-5 text-gray-400" />
              )}
              {t('builder.required')}
            </button>
          </div>

          {(question.question_type === 'single_choice' || question.question_type === 'multiple_choice') && (
            <div className="space-y-2">
              {parsedOptions.map((opt, idx) => (
                <div key={idx} className="flex items-center gap-2">
                  <span className="text-xs text-gray-400 w-5">{idx + 1}.</span>
                  <input
                    type="text"
                    value={opt}
                    disabled={disabled}
                    onChange={(e) => setOptionValue(idx, e.target.value)}
                    placeholder={t('builder.optionPlaceholder', { n: idx + 1 })}
                    className="flex-1 px-3 py-1.5 border border-gray-200 rounded-input text-sm focus:ring-2 focus:ring-primary-500"
                  />
                  {!disabled && (
                    <button onClick={() => removeOption(idx)} className="p-1 text-gray-400 hover:text-red-500">
                      <X className="w-3.5 h-3.5" />
                    </button>
                  )}
                </div>
              ))}
              {!disabled && (
                <button onClick={addOption} className="flex items-center gap-1 text-sm text-primary-600 hover:text-primary-700 font-medium">
                  <Plus className="w-3.5 h-3.5" />
                  {t('builder.addOption')}
                </button>
              )}
            </div>
          )}

          {question.question_type === 'rating' && (
            <div className="flex items-center gap-4">
              <div className="flex items-center gap-2">
                <label className="text-sm text-gray-600">{t('builder.ratingMin')}</label>
                <input
                  type="number"
                  value={ratingConfig.min}
                  disabled={disabled}
                  onChange={(e) => updateRatingConfig('min', e.target.value)}
                  className="w-16 px-2 py-1.5 border border-gray-200 rounded-input text-sm text-center"
                  min="0" max="10"
                />
              </div>
              <div className="flex items-center gap-2">
                <label className="text-sm text-gray-600">{t('builder.ratingMax')}</label>
                <input
                  type="number"
                  value={ratingConfig.max}
                  disabled={disabled}
                  onChange={(e) => updateRatingConfig('max', e.target.value)}
                  className="w-16 px-2 py-1.5 border border-gray-200 rounded-input text-sm text-center"
                  min="1" max="10"
                />
              </div>
              <div className="flex items-center gap-1 ml-4">
                {Array.from({ length: Math.max(0, ratingConfig.max - ratingConfig.min + 1) }, (_, i) => (
                  <Star key={i} className="w-5 h-5 text-yellow-400 fill-yellow-400" />
                ))}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
