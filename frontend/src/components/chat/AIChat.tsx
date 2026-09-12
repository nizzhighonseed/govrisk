import { Fragment, useEffect, useRef, useState } from 'react';
import type { FormEvent, ReactNode } from 'react';
import { Send } from 'lucide-react';

interface AIChatProps {
  messages: Array<{ id: string; role: 'user' | 'assistant'; content: string }>;
  onSend: (message: string) => void;
  suggestedQuestions?: string[];
  isTyping?: boolean;
}

function renderBold(line: string): ReactNode[] {
  const parts: ReactNode[] = [];
  const boldPattern = /\*\*(.+?)\*\*/g;
  let lastIndex = 0;
  let key = 0;
  let match = boldPattern.exec(line);
  while (match) {
    if (match.index > lastIndex) {
      parts.push(line.slice(lastIndex, match.index));
    }
    parts.push(<strong key={key++}>{match[1]}</strong>);
    lastIndex = match.index + match[0].length;
    match = boldPattern.exec(line);
  }
  if (lastIndex < line.length) {
    parts.push(line.slice(lastIndex));
  }
  return parts;
}

function formatAssistantContent(content: string): ReactNode {
  const lines = content.split('\n');
  return lines.map((line, lineIndex) => (
    <Fragment key={lineIndex}>
      {lineIndex > 0 && <br />}
      {renderBold(line)}
    </Fragment>
  ));
}

export function AIChat({
  messages,
  onSend,
  suggestedQuestions = [],
  isTyping = false,
}: AIChatProps) {
  const [input, setInput] = useState('');
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const el = scrollRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [messages, isTyping]);

  const handleSubmit = (e: FormEvent) => {
    e.preventDefault();
    const message = input.trim();
    if (!message || isTyping) return;
    onSend(message);
    setInput('');
  };

  return (
    <div className="flex h-full flex-col">
      <div ref={scrollRef} className="flex-1 space-y-4 overflow-y-auto p-6">
        {messages.length === 0 ? (
          <div>
            <h3 className="text-sm font-medium text-navy-900">
              Ask GovRisk AI...
            </h3>
            <div className="mt-4 grid gap-2 sm:grid-cols-2">
              {suggestedQuestions.map((question) => (
                <button
                  key={question}
                  type="button"
                  onClick={() => onSend(question)}
                  className="cursor-pointer bg-white border border-gray-200 rounded-xl p-3 text-sm text-gray-600 hover:bg-blue-50 hover:border-blue-200 hover:text-blue-700 transition-colors"
                >
                  {question}
                </button>
              ))}
            </div>
          </div>
        ) : (
          <>
            {messages.map((message) => {
              if (message.role === 'user') {
                return (
                  <div
                    key={message.id}
                    className="ml-auto max-w-[80%] bg-blue-600 text-white rounded-2xl rounded-br-md px-4 py-3 text-sm"
                  >
                    {message.content}
                  </div>
                );
              }
              return (
                <div
                  key={message.id}
                  className="max-w-[80%] bg-gray-100 text-navy-900 rounded-2xl rounded-bl-md px-4 py-3 text-sm"
                >
                  {formatAssistantContent(message.content)}
                </div>
              );
            })}
            {isTyping && (
              <div className="max-w-[80%] bg-gray-100 rounded-2xl rounded-bl-md px-4 py-3 text-sm">
                <div className="flex items-center gap-1">
                  <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-gray-400 [animation-delay:-0.3s]" />
                  <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-gray-400 [animation-delay:-0.15s]" />
                  <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-gray-400" />
                </div>
              </div>
            )}
          </>
        )}
      </div>

      <div className="bg-white border-t border-gray-200 p-4">
        <form onSubmit={handleSubmit} className="flex gap-3">
          <input
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder="Ask GovRisk AI..."
            className="flex-1 rounded-xl border border-gray-200 px-4 py-3 text-sm outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent"
          />
          <button
            type="submit"
            className="bg-blue-600 text-white rounded-xl px-6 py-3 text-sm font-medium hover:bg-blue-700 transition-colors"
          >
            <Send className="h-4 w-4" />
          </button>
        </form>
      </div>
    </div>
  );
}