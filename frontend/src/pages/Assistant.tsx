import { useState, useEffect } from 'react';
import { Bot } from 'lucide-react';
import { AIChat } from '../components/chat/AIChat';
import { sendAssistantMessage, getProjects } from '../services/api';
import { LoadingState } from '../components/ui/LoadingState';
import { RiskBadge } from '../components/ui/RiskBadge';
import { RiskScore } from '../components/ui/RiskScore';
import { useI18n } from '../i18n';

const suggestedQuestionKeys = [
  'assistant.suggest.highestRisk',
  'assistant.suggest.riverBasin',
  'assistant.suggest.costOverrun',
  'assistant.suggest.delayed',
  'assistant.suggest.drivers',
] as const;

interface Message {
  id: string;
  role: 'user' | 'assistant';
  content: string;
}

export default function Assistant() {
  const { t } = useI18n();
  const [messages, setMessages] = useState<Message[]>([]);
  const [isTyping, setIsTyping] = useState(false);
  const [projects, setProjects] = useState<any[]>([]);
  const [projectsLoading, setProjectsLoading] = useState(true);

  useEffect(() => {
    getProjects()
      .then(setProjects)
      .catch(() => setProjects([]))
      .finally(() => setProjectsLoading(false));
  }, []);

  const handleSend = async (content: string) => {
    if (isTyping) return;
    const userMessage: Message = {
      id: Date.now().toString(),
      role: 'user',
      content,
    };

    setMessages((prev) => [...prev, userMessage]);
    setIsTyping(true);

    try {
      const result = await sendAssistantMessage(content);
      const assistantMessage: Message = {
        id: (Date.now() + 1).toString(),
        role: 'assistant',
        content: result.reply,
      };
      setMessages((prev) => [...prev, assistantMessage]);
    } catch {
      const assistantMessage: Message = {
        id: (Date.now() + 1).toString(),
        role: 'assistant',
        content: t('assistant.failed'),
      };
      setMessages((prev) => [...prev, assistantMessage]);
    } finally {
      setIsTyping(false);
    }
  };

  return (
    <div className="mx-auto min-w-0 max-w-[1000px]">
      <div className="mb-6">
        <div className="flex items-center gap-3">
          <span className="rounded-xl bg-blue-50 p-2.5 ring-1 ring-inset ring-blue-100">
            <Bot className="h-7 w-7 text-blue-600" />
          </span>
          <div>
            <h1 className="text-2xl font-bold tracking-tight text-navy-900 lg:text-3xl">GovRisk AI</h1>
            <p className="text-sm font-medium text-gray-600">Infrastructure Intelligence Assistant</p>
          </div>
        </div>
        <p className="mt-2 text-sm text-gray-500">
          {t('assistant.description')}
        </p>
      </div>

      <div className="mb-8 overflow-hidden rounded-xl border border-gray-200 bg-white">
        <div className="flex items-center justify-between border-b border-gray-200 px-5 py-3">
          <h2 className="text-sm font-semibold text-navy-900">{t('assistant.monitoredProjects')}</h2>
        </div>
        {projectsLoading ? (
          <LoadingState text={t('assistant.loadingProjects')} />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[600px] text-left text-sm">
              <thead>
                <tr className="bg-gray-50 text-xs uppercase tracking-wider text-gray-500">
                  <th className="px-4 py-3 font-semibold lg:px-6">{t('assistant.project')}</th>
                  <th className="px-4 py-3 font-semibold">{t('assistant.riskLevel')}</th>
                  <th className="px-4 py-3 font-semibold">{t('assistant.riskScore')}</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100">
                {projects.map((project: any) => (
                  <tr key={project.id} className="transition-colors hover:bg-blue-50/40">
                    <td className="max-w-[320px] px-4 py-3 lg:px-6">
                      <div className="truncate font-medium text-navy-900" title={project.name}>
                        {project.name}
                      </div>
                    </td>
                    <td className="px-4 py-3">
                      <RiskBadge level={project.riskLevel} size="sm" />
                    </td>
                    <td className="px-4 py-3">
                      <RiskScore score={project.riskScore} size="sm" />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      <div className="flex h-[calc(100vh-13rem)] min-h-[440px] flex-col overflow-hidden rounded-xl border border-gray-200 bg-white">
        <AIChat
          messages={messages}
          onSend={handleSend}
          suggestedQuestions={messages.length === 0 ? suggestedQuestionKeys.map((k) => t(k)) : undefined}
          isTyping={isTyping}
        />
      </div>
    </div>
  );
}
