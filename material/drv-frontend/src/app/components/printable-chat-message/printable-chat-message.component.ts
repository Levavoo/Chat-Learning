import {
  Component,
  inject,
  Input,
  SecurityContext,
  OnInit,
} from '@angular/core';
import { DomSanitizer, SafeHtml } from '@angular/platform-browser';
import { RichtextComponent } from '@drv-ds/drv-design-system-ng';
import { ChatMessage, ChatSource } from '@models/bedrock-chat.models';
import { ChatMessageService } from '@services/chat-message.service';
import { sanitizeHtml } from '@utils/sanitize-html';

@Component({
  selector: 'drv-printable-chat-message',
  standalone: true,
  imports: [RichtextComponent],
  templateUrl: './printable-chat-message.component.html',
  styleUrl: './printable-chat-message.component.scss',
})
export class PrintableChatMessageComponent implements OnInit {
  @Input()
  public message!: ChatMessage;

  text: SafeHtml | null = null;
  private sources: ChatSource[] = [];
  private sanitizer = inject(DomSanitizer);
  private chatMessageService = inject(ChatMessageService);
  async ngOnInit() {
    let html = '';

    if (this.message?.content) {
      html = this.message.content.replace(
        /<button[^>]*>(.*?)<\/button>/g,
        '$1',
      );
    }
    if (this.message?.usedChunks?.length) {
      let quellenText = '';

      this.message.usedChunks.forEach((chunk) => {
        quellenText += `${chunk.sourceName} (Stand: ${chunk.publishingDate})<br>`;
      });

      html += `<strong>Quellen:</strong>${quellenText}`;
    }

    this.text = await this.chatMessageService.convertToHtml(html);
    this.text = this.convertLinksToUrls(this.text);
  }

  getSources(): ChatSource[] {
    if (this.sources.length === 0 && this.message?.content)
      this.sources = this.chatMessageService.extractSources(
        this.message.content,
      );
    return this.sources;
  }

  convertLinksToUrls(input: SafeHtml): SafeHtml {
    let html = this.sanitizer.sanitize(SecurityContext.HTML, input) || '';
    html = html
      .replace(/<\/a>(\s|<br\s*\/?>)*\./gi, '.</a> ')
      .replace(/&lt;\/a&gt;\./g, '.&lt;/a&gt;')
      .replace(/(<br\s*\/?>\s*)+/gi, '<br>');
    return this.sanitizer.bypassSecurityTrustHtml(sanitizeHtml(html));
  }
}
