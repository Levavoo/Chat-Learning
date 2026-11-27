import { SafeHtml } from '@angular/platform-browser';

export type {
  ChatInput,
  ChatInputMessage,
  ChatOutput,
  ChatOutputMessage,
  MessageChunk,
  MessageContent,
  MessageFeedback,
} from '../types';

import type { MessageChunk, MessageContent, MessageFeedback } from '../types';

export interface Message {
  role: string;
  content: MessageContent[];
  model?: string;
  feedback?: MessageFeedback | null;
  usedChunks?: MessageChunk[] | null;
  parent: string;
  messageId?: string | null;
}

export interface ChatMessage {
  id: string;
  role: string;
  content: string;
  html?: string | SafeHtml;
  sources?: string[];
  relatedDocuments?: MessageChunk[];
  usedChunks?: MessageChunk[];
}

export interface ChatSource {
  index: string;
  url: string;
  label: string;
  description: string;
}
