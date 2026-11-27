import { inject, Injectable } from '@angular/core';
import { ChatSource } from '@models/bedrock-chat.models';
import { BedrockChatService } from './bedrock-chat/bedrock-chat.service';
import { SafeHtml } from '@angular/platform-browser';

@Injectable({
  providedIn: 'root',
})
export class ChatMessageService {
  private readonly chatService = inject(BedrockChatService);

  extractSources(input: string): ChatSource[] {
    if (!input) return [];

    let index = 0;
    const sources: ChatSource[] = [];

    input.replace(
      /\\href\{(https?:\/\/[^}]+)\}\{([^}]+)\}\{([^}]+)\}/g,
      (match, url, label, description) => {
        index++;
        sources.push({
          index: index + '',
          url: url,
          label: label,
          description: description,
        });
        return '';
      },
    );

    return sources;
  }

  convertToHtml(input: string): Promise<SafeHtml> {
    input = input.replace(/ ?\[\^([\w@]+)\]/g, '');

    if (!input) {
      return this.chatService.processMarkdown('');
    }

    input = input.replace(/\\url\{(https?:\/\/[^}]+)\}/g, (match, url) => {
      return url;
    });

    input = input.replace(/ ?\[\d+\]/g, '');
    const processedHtml = this.chatService.processMarkdown(input);

    return processedHtml;
  }
}
