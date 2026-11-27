import { Component, inject, Input, OnChanges } from '@angular/core';
import { DomSanitizer, SafeHtml } from '@angular/platform-browser';
import { ButtonComponent } from '@drv-ds/drv-design-system-ng';
import { MessageChunk } from '@models/bedrock-chat.models';
import { MatomoService } from '@services/matomo/matomo.service';
import { marked } from 'marked';

@Component({
  selector: 'drv-related-documents-panel',
  imports: [ButtonComponent],
  templateUrl: './related-documents-panel.component.html',
  styleUrl: './related-documents-panel.component.scss',
})
export class RelatedDocumentsPanelComponent implements OnChanges {
  @Input()
  currentDocument!: MessageChunk;

  introText: SafeHtml = '';
  private readonly domSanitizer: DomSanitizer = inject(DomSanitizer);
  private readonly matomoService: MatomoService = inject(MatomoService);

  async ngOnChanges() {
    const contentText = this.currentDocument?.content ?? '';
    const parsed = await marked.parse(this.normalizeHintLabels(contentText));
    this.introText = this.domSanitizer.sanitize(1, parsed) ?? '';
  }

  // Dedupes and normalizes hint labels (e.g. "Unser Tipp:", "Bitte beachten Sie:")
  // to `> ##### Label:\n`, tolerating bold markers, mixed spacing and casing.
  normalizeHintLabels(
    input: string,
    labels: string[] = ['Unser Tipp:', 'Bitte beachten Sie:'],
    { anchorAtLineStart = false }: { anchorAtLineStart?: boolean } = {},
  ): string {
    let text = input;

    for (const rawLabel of labels) {
      const labelCore = rawLabel.replace(/[:\s]+$/, '').trim();
      const boundary = anchorAtLineStart ? '(^|\\n)(\\s*)' : '';
      const head = anchorAtLineStart ? '$1$2' : '';

      const singleLabel = String.raw`(?:\*{2}\s*)?${this.escapeRegex(
        labelCore,
      )}\s*:+\s*(?:\*{2}\s*)?`;
      const dedupe = new RegExp(
        `${boundary}(?:${singleLabel})(?:\\s*(?:${singleLabel}))+`,
        'gim',
      );
      text = text.replace(dedupe, `${head}${labelCore}: `);
      const normalizeOnce = new RegExp(`${boundary}${singleLabel}`, 'gim');
      text = text.replace(normalizeOnce, `${head}${labelCore}: `);
      const finalForm = new RegExp(
        `${boundary}${this.escapeRegex(labelCore)}:\\s*`,
        'gim',
      );
      text = text.replace(finalForm, `${head}> ##### ${labelCore}:\n`);
      const tidy = new RegExp(
        `${boundary}\\*\\*${this.escapeRegex(labelCore)}:\\*\\*\\s+`,
        'gim',
      );
      text = text.replace(tidy, `${head}**${labelCore}:**\n`);
    }
    return text;
  }

  escapeRegex(s: string): string {
    return s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  }

  goToBrochure(url: string): void {
    this.matomoService.trackEvent(
      'Chatbot',
      'Broschüre-Link',
      this.currentDocument?.brochureNumber ?? url,
    );
    window.open(url, '_blank', 'noopener, noreferrer ');
  }

  getBrochureButtonLabel(): string {
    if (this.currentDocument?.brochureNumber?.startsWith('faq')) {
      return 'Zu allen FAQs';
    }
    if (this.currentDocument.category === 'Merkblatt') {
      return 'Zum gesamten Merkblatt';
    }
    return 'Zur gesamten Broschüre';
  }
}
