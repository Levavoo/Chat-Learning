import {
  AfterViewInit,
  Component,
  forwardRef,
  inject,
  OnDestroy,
  OnInit,
  QueryList,
  ViewChildren,
} from '@angular/core';
import { FormsModule } from '@angular/forms';
import {
  ButtonbarComponent,
  ButtonComponent,
  CheckboxComponent,
  LinklistComponent,
  LinklistData,
  ModalComponent,
  ModalContentDirective,
  ModalService,
  NotificationComponent,
  NotificationService,
  TextareaComponent,
  SpinnerComponent,
  ModalActionsDirective,
} from '@drv-ds/drv-design-system-ng';
import { Subscription, throwError } from 'rxjs';

import { ChatPanelComponent } from '@components/chat-panel/chat-panel.component';
import { escapeHtml } from '@utils/sanitize-html';
import { detectReferralLinks } from '@utils/referral-links';
import {
  FeedbackComponent,
  LocalNotification,
} from '@components/feedback/feedback.component';
import { RenateSidePanelComponent } from '@components/renate-side-panel/renate-side-panel.component';
import { ChatMessage, MessageFeedback } from '@models/bedrock-chat.models';
import {
  feedbackModalId,
  FeedbackType,
  RawFeedbackRating,
} from '@models/feedback/feedback.model';
import {
  ExampleQuestionCategory,
  ExampleQuestionLinklistData,
} from '@models/messages/exampleQuestionLinklistData';
import {
  chatNotificationId,
  copyConversationIdSuccessNotification,
  exampleQuestions,
  feedbackErrorNotification,
  feedbackSuccessNotification,
  sessionDataDeleteSuccessful,
} from '@models/messages/messages.models';
import { BedrockChatService } from '@services/bedrock-chat/bedrock-chat.service';
import { DisclaimerService } from '@services/disclaimer.service';
import { MatomoService } from '@services/matomo/matomo.service';
import { FeedbackService } from '@services/feedback/feedback.service';
import { PrintPreviewComponent } from '@components/print-preview/print-preview.component';
import { HelpPageComponent } from '@components/help-page/help-page.component';
import { ButtonIconOnly } from '@models/button/button.models';
import { AsyncPipe } from '@angular/common';
import { ENV_CONFIG } from 'src/app/environment.token';

@Component({
  selector: 'drv-chatbot',
  standalone: true,
  imports: [
    AsyncPipe,
    ButtonbarComponent,
    ButtonComponent,
    ChatPanelComponent,
    CheckboxComponent,
    HelpPageComponent,
    PrintPreviewComponent,
    FeedbackComponent,
    FormsModule,
    LinklistComponent,
    ModalComponent,
    ModalContentDirective,
    NotificationComponent,
    RenateSidePanelComponent,
    TextareaComponent,
    SpinnerComponent,
    ModalActionsDirective,
  ],
  providers: [],
  templateUrl: './chatbot.component.html',
  styleUrl: './chatbot.component.scss',
})
export class ChatbotComponent implements OnInit, AfterViewInit, OnDestroy {
  @ViewChildren(forwardRef(() => CheckboxComponent))
  checkbox!: QueryList<CheckboxComponent>;

  @ViewChildren(forwardRef(() => TextareaComponent))
  textArea!: QueryList<TextareaComponent>;

  private readonly feedbackService: FeedbackService = inject(FeedbackService);
  private readonly environment = inject(ENV_CONFIG);

  public chatMessages: ChatMessage[] = [];
  showPanel = false;
  hidePanel = false;
  helpModalId = 'help-modal';
  cancelSessionId = 'cancel-session';
  isIntern = this.environment.intern;
  contactUrl = 'https://deutsche-rentenversicherung.de/renate-feedback';
  public welcomeMessage = '';
  public userInput = '';
  public exampleMessages: ExampleQuestionLinklistData[] =
    this.randomQuestions();
  public examplesVisible = true;

  public lastBotMessageIndex: number | null = null;
  public isLoading = false;
  public isStreamingActive = false;
  public historyLoading = true;
  public feedbackTrigger = 0;
  public chatNotificationId = chatNotificationId;
  rawFeedbackRating: RawFeedbackRating = {
    isMultiturn: false,
    isSingleturn: false,
    isFreeUserTest: false,
    isFinalFeedback: false,
    isPerTurnFeedback: false,
  };

  public buttons: ButtonIconOnly[] = [
    {
      label: 'Ihre Meinung zu Renate',
      kind: 'secondary',
      iconOnly: 'only',
      iconType: 'mail',
      disabled: false,
      buttonClick: () => {
        this.matomoService.trackEvent('Chatbot', 'Button', 'Ihre-Meinung');
        this.onContactUs();
      },
    },
    {
      label: 'Chatverlauf drucken',
      kind: 'secondary',
      iconOnly: 'only',
      iconType: 'print',
      disabled: false,
      buttonClick: () => {
        this.matomoService.trackEvent('Chatbot', 'Button', 'Drucken');
        window.print();
      },
    },
    {
      label: 'Hilfe zur Nutzung von Renate',
      kind: 'secondary',
      iconOnly: 'only',
      iconType: 'question-mark',
      disabled: false,
      buttonClick: () => this.openHelpModal(),
    },
  ];
  isFeedbackSent = false;
  private subscriptions: Subscription[] = [];

  feedbackModalId: string = feedbackModalId;
  feedbackPerTurn: FeedbackType = {};
  feedbackPerTurnMessageIds: ReadonlySet<string> = new Set();

  private readonly notificationService = inject(NotificationService);
  private readonly modalService = inject(ModalService);
  private readonly matomoService = inject(MatomoService);
  readonly bedrockChatService = inject(BedrockChatService);
  readonly disclaimerService = inject(DisclaimerService);

  readonly isDisclaimerAccepted$ =
    this.disclaimerService.getDisclaimerAccepted$();
  readonly isConsentAccepted$ = this.disclaimerService.getConsentAccepted$();

  async ngOnInit(): Promise<void> {
    this.subscriptions.push(
      this.bedrockChatService.focus$.subscribe((state) => {
        if (state === 'focus') this.focusOnTextArea();
        if (state === 'scroll') this.scrollOnTextArea();
      }),
      this.bedrockChatService.isLoading$.subscribe(
        (isLoading) => (this.isLoading = isLoading),
      ),
      this.bedrockChatService.chatMessage$.subscribe((msg) => {
        if (msg.role === 'assistant' && msg.content) {
          for (const category of detectReferralLinks(msg.content)) {
            this.matomoService.trackEvent(
              'Chatbot',
              'Weiterleitung-angezeigt',
              category,
            );
          }
        }
      }),
    );

    this.historyLoading = true;
    try {
      await this.bedrockChatService.initialize();
    } finally {
      this.historyLoading = false;
    }

    this.chatMessages = this.bedrockChatService.chatMessages;

    if (this.chatMessages.length > 1) {
      this.examplesVisible = false;
    }
    this.rawFeedbackRating = structuredClone(
      this.feedbackService.rawFeedbackRating,
    );
    this.disclaimerService.initConsentSaving(
      this.bedrockChatService.conversationId,
    );
    if (this.isIntern) {
      localStorage.setItem('isMultiturn', '');
      localStorage.setItem('usedScenario', '');
    }
    if (this.isIntern) {
      localStorage.setItem('isMultiturn', '');
      localStorage.setItem('usedScenario', '');
    }
  }

  ngAfterViewInit(): void {
    this.focusOnTextArea();
    this.subscriptions.push(
      this.textArea?.changes.subscribe(() => this.focusOnTextArea()),
    );
  }

  ngOnDestroy(): void {
    this.subscriptions.forEach((sub) => {
      sub.unsubscribe();
    });
  }

  private focusOnTextArea(): void {
    if (this.textArea?.first) {
      const inputRef = this.textArea.first.input();
      if (inputRef) inputRef.nativeElement.focus();
    }
  }

  private scrollOnTextArea(): void {
    if (this.textArea?.first) {
      const inputRef = this.textArea.first.input();
      if (inputRef) {
        inputRef.nativeElement.scrollIntoView({
          behavior: 'smooth',
          block: 'end',
        });
        inputRef.nativeElement.focus();
      }
    }
  }

  onSendMessage(firstInputType: 'Freitext' | 'Beispielfrage' = 'Freitext') {
    if (!this.userInput.trim()) return;

    const isFirstInput = !this.bedrockChatService.chatMessages.some(
      (message) => message.role === 'user',
    );

    this.bedrockChatService.isLoading$.next(true);

    const msg: ChatMessage = {
      id: this.bedrockChatService.getChatMessageId() + '',
      role: 'user',
      content: this.userInput,
      html: '<strong>Ich:</strong> ' + escapeHtml(this.userInput),
    };

    this.bedrockChatService.chatMessage$.next(msg);
    if (isFirstInput) {
      this.matomoService.trackEvent('Chatbot', 'Erste-Eingabe', firstInputType);
    }
    this.examplesVisible = false;
    this.bedrockChatService.setChatStreamResponse(
      this.bedrockChatService.chatMessages.map((message) => ({
        role: message.role,
        content: message.content,
      })),
    );

    const active = document.activeElement as HTMLElement;
    setTimeout(() => {
      active?.blur();
    }, 0);
    this.userInput = '';
  }

  onEnter(event: Event) {
    event.preventDefault();
    if (!this.userInput.trim()) return;
    this.onSendMessage();
  }

  onDisclaimerCheckboxEnter(event: Event) {
    event.preventDefault();
    this.setDisclaimerAccepted();
  }

  onConsentCheckboxEnter(event: Event) {
    event.preventDefault();
    this.setConsentAccepted();
  }

  setDisclaimerAccepted() {
    this.disclaimerService.toggleDisclaimer();
  }

  setConsentAccepted() {
    this.disclaimerService.toggleConsent();
  }

  onCopyConversationId() {
    navigator.clipboard.writeText(
      this.bedrockChatService.conversationId.toString(),
    );
    this.notificationService.update(copyConversationIdSuccessNotification);
  }

  onExampleMsgClick(event: { item: LinklistData; event: MouseEvent }) {
    this.userInput = event.item.text;
    this.onSendMessage('Beispielfrage');
    this.examplesVisible = false;
  }

  isFeedbackProvidable(): boolean {
    return (
      !this.isFeedbackSent &&
      this.bedrockChatService.chatMessages.length > 1 &&
      !this.isLoading
    );
  }

  openHelpModal() {
    this.matomoService.trackEvent('Chatbot', 'Button', 'Hilfe');
    this.modalService.updateModal({
      id: this.helpModalId,
      open: true,
    });
  }

  onCancelSession(): void {
    this.modalService.updateModal({
      id: this.cancelSessionId,
      open: true,
    });
  }

  doCancelSession(): void {
    this.matomoService.trackEvent(
      'Chatbot',
      'Button',
      'Einwilligung-widerrufen',
    );
    this.closeModal();
    this.subscriptions.push(
      this.bedrockChatService.deleteSessionData().subscribe({
        next: () => {
          this.notificationService.update(sessionDataDeleteSuccessful);
          setTimeout(() => {
            window.location.hash = '/chat';
            window.location.reload();
          }, 3000);
        },
        error: (error) => {
          console.error('Error deleting session data', error);
          return throwError(() => error);
        },
      }),
    );
  }

  closeModal(): void {
    this.modalService.updateModal({
      id: this.cancelSessionId,
      open: false,
    });
  }

  feedbackSent(successfull: boolean): void {
    if (this.feedbackPerTurn.type === 'conversation') {
      this.isFeedbackSent = successfull;
    }
    if (this.isIntern) {
      this.showPanel = !successfull;
    }
  }

  notificationSent(localNotification: LocalNotification) {
    this.notificationService.update(localNotification);
  }

  getLastAssistantMessageId(): string {
    const assistantMessages = this.bedrockChatService.chatMessages
      .filter((msg) => msg.role === 'assistant')
      .reverse();
    return assistantMessages.length > 0 ? assistantMessages[0].id : '';
  }

  openFeedbackModal(): void {
    this.showPanel = true;
    this.hidePanel = false;
  }

  // One random question per category (Rente, Versicherung, Reha, Sonstiges), shuffled.
  randomQuestions(): ExampleQuestionLinklistData[] {
    const result: ExampleQuestionLinklistData[] = [];

    const categories = [
      ExampleQuestionCategory.Rente,
      ExampleQuestionCategory.Versicherung,
      ExampleQuestionCategory.Reha,
      ExampleQuestionCategory.Sonstiges,
    ];

    for (const category of categories) {
      const questions = exampleQuestions.filter((q) => q.category === category);

      if (questions.length > 0) {
        const randomIndex = Math.floor(Math.random() * questions.length);
        result.push(questions[randomIndex]);
      }
    }
    return result.sort(() => Math.random() - 0.5);
  }

  closeDocument() {
    this.showPanel = false;
    this.hidePanel = true;
  }

  onContactUs(): void {
    window.open(this.contactUrl, '_blank', 'noopener, noreferrer ');
  }

  startNewConversation(): void {
    this.bedrockChatService.clearConversation();
    this.chatMessages = this.bedrockChatService.chatMessages;
    this.examplesVisible = true;
    this.isFeedbackSent = false;
    this.feedbackPerTurnMessageIds = new Set();
    localStorage.setItem('isMultiturn', '');
    localStorage.setItem('usedScenario', '');
    this.focusOnTextArea();
  }

  public saveFeedback(feedback: MessageFeedback, currentMessageId?: string) {
    const conversationId = this.bedrockChatService.conversationId;
    const messageId = currentMessageId
      ? currentMessageId
      : this.getLastAssistantMessageId();
    if (!conversationId || !messageId) {
      console.error('Cannot submit feedback: missing IDs', {
        conversationId: conversationId,
        messageId: messageId,
      });
      this.notificationSent(feedbackErrorNotification);
      return;
    }

    this.subscriptions.push(
      this.feedbackService
        .saveFeedback(feedback, conversationId, messageId)
        .subscribe({
          next: () => {
            this.notificationSent(feedbackSuccessNotification);
            if (this.feedbackPerTurn.type === 'perTurn') {
              this.feedbackPerTurnMessageIds = new Set([
                ...this.feedbackPerTurnMessageIds,
                messageId,
              ]);
            }
            this.feedbackSent(true);
            this.feedbackTrigger++;
          },
          error: () => {
            this.notificationSent(feedbackErrorNotification);
            this.feedbackSent(false);
          },
        }),
    );
  }

  /**
   * Submits the feedback to API endpoint and stores locally as backup
   */
  submitOnWasHelpful(event: FeedbackType): void {
    this.rawFeedbackRating.helpfulness = event.value;
    this.saveFeedback(
      {
        comment: this.rawFeedbackRating.comment,
        helpfulness: this.rawFeedbackRating.helpfulness
          ? this.rawFeedbackRating.helpfulness
          : null,
        isFinalFeedback: false,
        isFreeUserTest: false,
        isMultiturn: false,
        isSingleturn: false,
      } as MessageFeedback,
      event.messageId,
    );
  }
  /**
   * Submits the feedback per conversation to API endpoint and stores locally as backup
   */
  sendFeedbackPerConversation(): void {
    this.feedbackPerTurn = {
      messageId: '',
      type: 'conversation',
    };
    this.openFeedbackModal();
  }
  /**
   * Submits the feedback per message to API endpoint and stores locally as backup
   */
  sendFeedbackPerTurn(event: FeedbackType): void {
    this.feedbackPerTurn = {
      messageId: event.messageId,
      type: event.type,
    };
    this.openFeedbackModal();
  }
}
