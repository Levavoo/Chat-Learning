import {
  AfterViewChecked,
  AfterViewInit,
  Component,
  inject,
  Input,
  HostListener,
  Output,
  EventEmitter,
  SimpleChanges,
  OnChanges,
} from '@angular/core';
import { RelatedDocumentsPanelComponent } from '@components/related-documents-panel/related-documents-panel.component';
import { RenateIconComponent } from '@components/renate-icon/renate-icon.component';
import { RenateSidePanelComponent } from '@components/renate-side-panel/renate-side-panel.component';
import {
  ButtonbarComponent,
  ButtonComponent,
  IcontextComponent,
} from '@drv-ds/drv-design-system-ng';
import { ChatMessage, MessageChunk } from '@models/bedrock-chat.models';
import { BedrockChatService } from '@services/bedrock-chat/bedrock-chat.service';
import { MatomoService } from '@services/matomo/matomo.service';
import { classifyReferralLink } from '@utils/referral-links';
import { ChatMessageComponent } from './chat-message/chat-message.component';
import { UserFeedback } from '@models/feedback/feedback.model';

@Component({
  selector: 'drv-chat-panel',
  standalone: true,
  imports: [
    RelatedDocumentsPanelComponent,
    RenateIconComponent,
    IcontextComponent,
    RenateSidePanelComponent,
    ChatMessageComponent,
    ButtonComponent,
    ButtonbarComponent,
  ],
  templateUrl: './chat-panel.component.html',
  styleUrl: './chat-panel.component.scss',
})
export class ChatPanelComponent
  implements AfterViewInit, AfterViewChecked, OnChanges
{
  @Input()
  public chatMessages: ChatMessage[] = [];
  @Input() isIntern!: boolean;
  @Input() isFeedbackSent = false;
  @Input() feedbackTrigger = 0;
  @Input() feedbackPerTurnMessageIds: ReadonlySet<string> = new Set();
  @Output() messageFeedbackEvent = new EventEmitter<{
    messageId: string;
    value: UserFeedback;
  }>();
  @Output() feedbackPerTurnEvent = new EventEmitter<{
    messageId: string;
    type: string;
  }>();

  public showPanel = false;
  public currentDocument: MessageChunk = {} as MessageChunk;
  providedFeedbacks = new Map<number, UserFeedback>();
  lastClickedButtonIndex: number | undefined;
  lastClickedFeedback: UserFeedback | null = null;
  showFeedbackPanel = false;
  hideFeedbackPanel = false;
  private messageCount = 0;
  private bedrockChatService: BedrockChatService = inject(BedrockChatService);
  private matomoService: MatomoService = inject(MatomoService);
  UserFeedback = UserFeedback;
  ngAfterViewChecked() {
    if (this.messageCount < this.bedrockChatService.chatMessages.length) {
      this.messageCount = this.bedrockChatService.chatMessages.length;
    }
  }

  ngAfterViewInit(): void {
    this.messageCount = this.bedrockChatService.chatMessages.length;
  }

  openDocument(brochure: MessageChunk) {
    this.currentDocument = brochure;
    this.showPanel = true;
    this.matomoService.trackEvent(
      'Chatbot',
      'Quelle-angezeigt',
      brochure.sourceName ?? 'Unbekannt',
    );
  }

  closeDocument() {
    this.showPanel = false;
  }

  @HostListener('document:keydown.escape')
  onEsc() {
    if (this.showPanel) {
      this.closeDocument();
    }
  }

  // Intercepts <a> clicks inside <drv-chat-message> for B4/B6 tracking. Add a guard here if any new <a>-rendering child is introduced.
  @HostListener('click', ['$event'])
  onChatPanelClick(event: MouseEvent): void {
    const target = event.target as HTMLElement;
    const anchor = target.closest('a') as HTMLAnchorElement | null;
    if (!anchor) return;

    const chatMessage = anchor.closest('drv-chat-message');
    if (!chatMessage) return;

    const messageIndex = chatMessage.getAttribute('data-message-index');

    if (messageIndex === '0') {
      const linkText = anchor.textContent?.trim() ?? '';
      if (linkText) {
        this.matomoService.trackEvent('Chatbot', 'Welcome-Link', linkText);
      }
      return;
    }

    const href = anchor.getAttribute('href') ?? '';
    const category = classifyReferralLink(href);
    if (category) {
      this.matomoService.trackEvent('Chatbot', 'Weiterleitung', category);
    }
  }

  isDisabled(index: number): boolean {
    return this.providedFeedbacks.has(index);
  }

  isPerTurnFeedbackDisabled(messageId: string): boolean {
    return (
      this.feedbackPerTurnMessageIds.has(messageId) ||
      localStorage.getItem('isMultiturn') === 'false'
    );
  }

  isFeedbackProvided(index: number, selectedFeedback: UserFeedback): boolean {
    return (
      this.providedFeedbacks.has(index) &&
      this.providedFeedbacks.get(index) === selectedFeedback
    );
  }

  ngOnChanges(changes: SimpleChanges): void {
    if (changes['feedbackTrigger']) {
      if (
        this.isFeedbackSent &&
        this.lastClickedButtonIndex !== undefined &&
        this.lastClickedFeedback
      ) {
        this.providedFeedbacks.set(
          this.lastClickedButtonIndex,
          this.lastClickedFeedback,
        );
        this.lastClickedButtonIndex = undefined;
        this.lastClickedFeedback = null;
      }
    }
  }

  sendMessageFeedback(
    message: ChatMessage,
    userFeedback: UserFeedback,
    buttonArrayIndex: number,
  ): void {
    this.lastClickedButtonIndex = buttonArrayIndex;
    this.lastClickedFeedback = userFeedback;
    this.isFeedbackSent = true;
    this.matomoService.trackEvent(
      'Chatbot',
      'Button',
      'Feedback-' + userFeedback,
    );
    this.messageFeedbackEvent.emit({
      messageId: message.id,
      value: userFeedback,
    });
  }

  /**
   * Triggered after sending a feedback
   *
   * @param message
   */
  feedbackSent(successfull: boolean): void {
    this.isFeedbackSent = successfull;
    if (this.isIntern) {
      this.showPanel = !successfull;
    }
  }

  /**
   * Open feedback modal
   */
  openFeedbackModal(message: ChatMessage): void {
    this.feedbackPerTurnEvent.emit({
      messageId: message.id,
      type: 'perTurn',
    });
  }
}
