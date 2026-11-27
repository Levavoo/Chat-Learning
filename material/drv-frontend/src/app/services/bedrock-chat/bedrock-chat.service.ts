import {
  HttpClient,
  HttpErrorResponse,
  HttpHeaders,
} from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { DomSanitizer, SafeHtml } from '@angular/platform-browser';
import { LocalNotification } from '@components/feedback/feedback.component';
import {
  ChatInput,
  ChatMessage,
  ChatOutput,
  Message,
  MessageChunk,
  MessageContent,
} from '@models/bedrock-chat.models';
import {
  ASSISTANT_NAME_PREFIX,
  chatTimeoutNotification,
  FALLBACK_ERROR_STATUSES,
  welcomeMessage,
} from '@models/messages/messages.models';
import { marked } from 'marked';
import { sanitizeHtml } from '@utils/sanitize-html';
import {
  Observable,
  Subject,
  TimeoutError,
  catchError,
  tap,
  throwError,
  timeout,
} from 'rxjs';
import { v4 as uuidv4 } from 'uuid';
import { ApiProxyService } from '../api-proxy/api-proxy.service';
import { SessionService } from '../session.service';
import { environment } from '../../../environments/environment';
import { getChatNotification } from 'src/app/utils/chat-error-notification.utils';

@Injectable({
  providedIn: 'root',
})
export class BedrockChatService {
  private headers = new HttpHeaders({
    'Content-Type': 'application/json',
  });

  public chatMessages: ChatMessage[] = [];
  public chatMessage$: Subject<ChatMessage> = new Subject<ChatMessage>();

  public isLoading$: Subject<boolean> = new Subject<boolean>();
  public focus$: Subject<'focus' | 'scroll'> = new Subject<
    'focus' | 'scroll'
  >();

  public messages: Message[] = [];
  public relatedDocuments: MessageChunk[] = [];

  private readonly http = inject(HttpClient);
  private readonly apiProxy = inject(ApiProxyService);
  private readonly sanitizer: DomSanitizer = inject(DomSanitizer);
  private readonly sessionService = inject(SessionService);

  constructor() {
    this.markdownRenderer();

    this.chatMessage$.subscribe((chatMessage) => {
      this.chatMessages.push(chatMessage);
    });
  }

  // Idempotent — call from ngOnInit; adds the welcome message only on first run.
  async initialize(): Promise<void> {
    if (this.chatMessages.length === 0) {
      await this.addWelcomeMessage();
    }
  }

  // Global marked renderer override so every link opens in a new tab.
  private markdownRenderer() {
    marked.use({
      renderer: {
        link({ href, title, text }) {
          const titleAttr = title ? ` title="${title}"` : '';
          return `<a href="${href}" target="_blank" rel="noopener noreferrer"${titleAttr}>${text}</a>`;
        },
      },
    });
  }

  public async addWelcomeMessage(): Promise<void> {
    const welcomeText = welcomeMessage;

    const markedHtml = await marked(welcomeText);
    const msg: ChatMessage = {
      id: '' + this.getChatMessageId(),
      role: 'assistant',
      content: welcomeText,
      html: this.sanitizer.bypassSecurityTrustHtml(sanitizeHtml(markedHtml)),
      sources: [],
    };
    this.chatMessages.push(msg);
  }

  getChatMessageId(): string {
    if (this.messages.length >= 1) {
      return this.messages[this.messages.length - 1].parent;
    }
    return '';
  }

  public get conversationId(): string {
    return this.sessionService.getSessionId();
  }

  public clearConversation(): void {
    this.chatMessages = [];
    this.messages = [];
    this.relatedDocuments = [];
    this.sessionService.createNewSession();
    this.addWelcomeMessage();
  }

  postChatMessage(message: string): Observable<ChatOutput> {
    const sessionId = this.sessionService.getSessionId();
    const messageId = `${sessionId}#${uuidv4()}`;

    const chatInput: ChatInput = {
      conversationId: sessionId,
      message: {
        content: [{ contentType: 'text', body: message }],
        messageId: messageId,
      },
    };

    return this.http
      .post<ChatOutput>(this.apiProxy.conversationUrl, chatInput, {
        headers: this.headers,
      })
      .pipe(
        timeout(30000),
        catchError((error) => {
          if (error instanceof TimeoutError) {
            return throwError(() => ({
              message: 'Client timeout.',
              notification: chatTimeoutNotification,
            }));
          }
          if (FALLBACK_ERROR_STATUSES.includes(error?.status)) {
            (
              error as HttpErrorResponse & {
                notification?: LocalNotification;
              }
            ).notification = getChatNotification(error);
            return throwError(() => error);
          }
          return throwError(() => error);
        }),
      );
  }

  setChatStreamResponse(messages: { role: string; content: string }[]): void {
    const lastUserMessage = messages.filter((m) => m.role === 'user').pop();
    if (!lastUserMessage) {
      this.handleError('No user message found');
      return;
    }

    this.isLoading$.next(true);

    this.postChatMessage(lastUserMessage.content)
      .pipe(
        tap((response) => {
          this.storeMessage(response);
        }),
      )
      .subscribe({
        next: async (response) => {
          const processed = await this.processMessageResponse(
            response.message,
            [],
          );
          this.chatMessage$.next(processed);
          this.isLoading$.next(false);
          this.focus$.next('scroll');
        },
        error: (err) => this.handleError(err),
      });
  }

  public deleteSessionData(): Observable<{ status: string }> {
    const conversationId = this.sessionService.getSessionId();
    const deleteUrl = `${this.apiProxy.deleteSessionUrl}/${conversationId}`;

    return this.http.delete<{ status: string }>(deleteUrl);
  }

  // Keyed on `documentId` (backend-stable, never the raw S3 URI) because
  // `brochureNumber`/`sourceName` can fail to resolve and would list the same
  // brochure twice when a single chunk lost its metadata (#676, security fix #871).
  private documentKey(doc: MessageChunk): string {
    if (doc.documentId) {
      return doc.documentId;
    }
    return doc.brochureNumber || `unknown-${doc.sourceIndex ?? 0}`;
  }

  // Chunks with unresolved metadata inherit from a sibling of the same document
  // so the surviving dedupe entry keeps the official title.
  private adoptSiblingMetadata(documents: MessageChunk[]): MessageChunk[] {
    return documents.map((doc) => {
      if (doc.brochureNumber) {
        return doc;
      }
      const resolved = documents.find(
        (candidate) =>
          !!candidate.brochureNumber &&
          this.documentKey(candidate) === this.documentKey(doc),
      );
      if (!resolved) {
        return doc;
      }
      return {
        ...doc,
        brochureNumber: resolved.brochureNumber,
        sourceName: resolved.sourceName,
        publishingDate: resolved.publishingDate ?? doc.publishingDate,
        brochureUrl: resolved.brochureUrl ?? doc.brochureUrl,
        category: resolved.category ?? doc.category,
      };
    });
  }

  private cleanSourceName(sourceName: string): string {
    return sourceName
      .replace(/\.html\.md$/g, '')
      .replace(/\.(md|pdf)$/gi, '')
      .replace(/_\d{4}$/, '')
      .replace(/^[A-Za-z]{1,3}[0-9]{1,3} [-|–] /g, '')
      .replace(/\(.*?\)[_-\d\w]*/, '');
  }

  private cleanRelatedDocuments(documents: MessageChunk[]): MessageChunk[] {
    if (!documents) return [];
    const enriched = this.adoptSiblingMetadata(documents);
    let unicDocuments: MessageChunk[] = enriched.filter(
      (value, index, self) => {
        return (
          self.findIndex(
            (d) => this.documentKey(d) === this.documentKey(value),
          ) === index
        );
      },
    );
    enriched.forEach((doc) => {
      unicDocuments = this.composeUsedChanksFromSameBrochure(
        doc,
        unicDocuments,
      );
    });

    unicDocuments = unicDocuments.map((doc) => {
      const newSourceName = this.cleanSourceName(doc.sourceName ?? '');

      // Strip the "**↓**" marker only; pipes must survive — they are GFM table
      // syntax, and dropping them collapses tables into a paragraph plus a stray <hr>.
      const cleanedContent = doc.content?.replace(/\*\*↓\*\*/g, '');

      return { ...doc, sourceName: newSourceName, content: cleanedContent };
    });

    unicDocuments = unicDocuments.map((el) => {
      if (this.containTableContent(el.content)) {
        const adjustedContentWithTable = this.adjustmentTableHeader(el.content);
        return { ...el, content: adjustedContentWithTable };
      } else {
        return el;
      }
    });
    return unicDocuments;
  }

  private containTableContent(content: string): boolean {
    const lines = content?.split('\n');
    if (lines) {
      for (let i = 0; i < lines.length - 1; i++) {
        const current = lines[i].trim();
        const next = lines[i + 1].trim();

        const isRow =
          current.startsWith('|') &&
          current.endsWith('|') &&
          current.includes('|');

        const isSeparator = /^\|\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)+\|?$/.test(
          next,
        );

        if (isRow && isSeparator) {
          return true;
        }
      }
    }

    return false;
  }

  private adjustmentTableHeader(content: string): string {
    const lines = content.split('\n');
    const fixed: string[] = [];
    let separatorTh = '';

    for (let i = 0; i < lines.length; i++) {
      const current = lines[i].trim();
      const next = (lines[i + 1] || '').trim();

      const isEmptyHeaderRow =
        current.startsWith('|') &&
        current.endsWith('|') &&
        !/[^\s|]/.test(current);

      // Empty header followed by a separator: drop the header, hold the separator for after the real header.
      if (isEmptyHeaderRow && this.isSeparatorRow(next)) {
        separatorTh = next;
        continue;
      }
      // Only drop a separator while relocating a captured one; a correctly-placed separator must survive
      // (otherwise GFM detection breaks and the table renders as raw pipes), and never emit two in a row.
      if (this.isSeparatorRow(current)) {
        if (separatorTh.length > 0) {
          continue;
        }
        if (!this.isSeparatorRow((fixed[fixed.length - 1] || '').trim())) {
          fixed.push(lines[i]);
        }
        continue;
      }
      if (separatorTh.length > 0) {
        fixed.push(lines[i]);
        fixed.push(separatorTh);
        separatorTh = '';
      } else {
        fixed.push(lines[i]);
      }
    }
    return fixed.join('\n');
  }

  private isSeparatorRow(row: string): boolean {
    return /^\|\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)+\|?$/.test(row);
  }

  private composeUsedChanksFromSameBrochure(
    doc: MessageChunk,
    unicDocuments: MessageChunk[],
  ): MessageChunk[] {
    return unicDocuments.map((d) =>
      this.documentKey(d) === this.documentKey(doc) &&
      d.sourceIndex !== doc.sourceIndex
        ? { ...d, content: d.content.concat('\n\n', doc.content) }
        : d,
    );
  }

  private async handleError(err: unknown): Promise<void> {
    if (!environment.name || environment.name !== 'prod') {
      console.error('Chat stream error:', err);
    }
    this.isLoading$.next(false);
    if (err instanceof HttpErrorResponse) {
      this.addErrorChatMessage(getChatNotification(err));
    }
    this.focus$.next('focus');
  }

  private async addErrorChatMessage(
    notification: LocalNotification,
  ): Promise<void> {
    const text = notification.text;
    if (text) {
      const markedHtml1 = await marked(text);
      const msg: ChatMessage = {
        id: '' + this.getChatMessageId(),
        role: 'error',
        content: text,
        html: this.sanitizer.bypassSecurityTrustHtml(sanitizeHtml(markedHtml1)),
        sources: [],
      };
      this.chatMessages.push(msg);
    }
  }

  private storeMessage(response: ChatOutput): void {
    const messageForStorage: Message = {
      ...response.message,
      feedback: response.message.feedback || undefined,
      usedChunks: response.message.usedChunks || undefined,
    };
    this.messages.push(messageForStorage);
  }

  private async processMessageResponse(
    messageData: ChatOutput['message'],
    relatedDocuments: MessageChunk[],
  ): Promise<ChatMessage> {
    let textContent = Array.isArray(messageData.content)
      ? messageData.content
          .filter((c: MessageContent) => c.contentType === 'text')
          .map((c: MessageContent) => c.body)
          .join('')
      : (messageData.content as unknown as string) || '';

    // Strip trailing "Quellen"/"Sources" section (case-insensitive, optional **).
    textContent = textContent
      .replace(
        /(?:\r\n|\r|\n)\s*(?:\*\*)?(?:Quellen|Sources):?(?:\*\*)?[\s\S]*$/i,
        '',
      )
      .trim();

    textContent = ASSISTANT_NAME_PREFIX + textContent;

    const sourceReferences = this.extractSourceReferences(textContent);
    const processedHtml = await this.processMarkdown(textContent);

    relatedDocuments = this.cleanRelatedDocuments(relatedDocuments);
    const usedChunks = messageData.usedChunks
      ? this.cleanRelatedDocuments(messageData.usedChunks)
      : undefined;

    return {
      id: messageData.messageId || messageData.parent,
      role: 'assistant',
      content: textContent,
      html: processedHtml,
      sources: sourceReferences || [],
      relatedDocuments: relatedDocuments,
      usedChunks,
    };
  }
  // SECURITY: marked() output is run through DOMPurify (sanitizeHtml) before
  // bypassSecurityTrustHtml; the bypass is needed because Angular's default
  // sanitizer strips classes we rely on for citations.
  async processMarkdown(text: string): Promise<SafeHtml> {
    let processedText = text;

    // Normalize indented list items (2-3 spaces -> 4) so marked treats them as lists.
    processedText = processedText.replace(
      /^(\s{2,3})([•\-*]|\d+\.)\s/gm,
      '    $2 ',
    );

    // Strip tool-use footnote refs and plain [n] citation markers; usedChunks already carries this.
    processedText = processedText
      .replace(/ ?\[\^[^\]]*\](?::\d+)?/gm, '')
      .replace(/ ?\[\d+\]/g, '');
    marked.use({
      gfm: true,
      breaks: true,
    });

    let markedHtml = await marked(processedText);

    // Collapse marked's extra <p> inside <li>, and drop duplicate numbering at <li> start.
    markedHtml = markedHtml
      .replace(/<li>\s*<p>/g, '<li>')
      .replace(/<\/p>\s*<\/li>/g, '</li>')
      .replace(/<li>(\d+)\.\s+/g, '<li>');

    markedHtml = markedHtml.replace(/SOURCE_LINK_\d+/g, '');

    return this.sanitizer.bypassSecurityTrustHtml(sanitizeHtml(markedHtml));
  }

  // Extracts source refs in `[^tooluse_ID@NUMBER]`; falls back to synthetic ids from `SOURCE_LINK_<n>`.
  private extractSourceReferences(text: string): string[] {
    const sourceRegex = /\[\^?(?:[a-zA-Z0-9_-]+@)?(\d+)\]/gm;
    const matches: string[] = [];
    let match: RegExpExecArray | null;

    while ((match = sourceRegex.exec(text)) !== null) {
      if (match[1]) {
        matches.push(match[1]);
      }
    }

    if (matches.length === 0) {
      const alternateLinkRegex = /SOURCE_LINK_(\d+)/g;
      const sourceNums: number[] = [];

      while ((match = alternateLinkRegex.exec(text)) !== null) {
        if (match[1]) {
          const sourceNum = parseInt(match[1], 10);
          if (!isNaN(sourceNum) && !sourceNums.includes(sourceNum)) {
            sourceNums.push(sourceNum);
          }
        }
      }

      sourceNums.forEach((num) => {
        matches.push(`source_${num}`);
      });
    }

    return [...new Set(matches)];
  }
}
