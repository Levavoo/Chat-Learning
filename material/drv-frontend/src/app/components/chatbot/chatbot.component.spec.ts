import { QueryList } from '@angular/core';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { ActivatedRoute } from '@angular/router';
import { By } from '@angular/platform-browser';
import {
  LinklistData,
  NotificationService,
  TextareaComponent,
} from '@drv-ds/drv-design-system-ng';
import {
  ExampleQuestionCategory,
  ExampleQuestionLinklistData,
} from '@models/messages/exampleQuestionLinklistData';
import { BedrockChatService } from '@services/bedrock-chat/bedrock-chat.service';
import { BehaviorSubject, Observable, of, Subject, throwError } from 'rxjs';
import { ChatbotComponent } from './chatbot.component';
import { FeedbackComponent } from '@components/feedback/feedback.component';
import { FeedbackService } from '@services/feedback/feedback.service';
import { MatomoService } from '@services/matomo/matomo.service';
import { feedbackErrorNotification } from '@models/messages/messages.models';
import { MessageFeedback } from '@models/bedrock-chat.models';
import { UserFeedback } from '@models/feedback/feedback.model';
import { ApiProxyService } from '@services/api-proxy/api-proxy.service';
import { provideHttpClient } from '@angular/common/http';
import { ENV_CONFIG } from 'src/app/environment.token';

describe('ChatbotComponent', () => {
  let component: ChatbotComponent;
  let fixture: ComponentFixture<ChatbotComponent>;

  interface ActivatedRouteMock {
    data: Observable<{ result: string }>;
  }

  interface BedrockChatServiceMock {
    chatMessages: { id?: string; role?: string }[];
    notificationId: string;
    focus$: Subject<void>;
    isLoading$: BehaviorSubject<boolean>;
    chatMessage$: Subject<unknown>;
    conversationId: string;
    getChatMessageId: () => string;
    setChatStreamResponse: jasmine.Spy;
    deleteSessionData?: jasmine.Spy;
    clearConversation?: () => void;
  }

  interface NotificationServiceMock {
    notifications: {
      subscribe: () => { unsubscribe(): void };
    };
    update: jasmine.Spy;
  }

  let feedbackServiceMock: jasmine.SpyObj<FeedbackService>;
  let activatedRouteMock: ActivatedRouteMock;
  let bedrockChatServiceMock: BedrockChatServiceMock;
  let notificationServiceMock: NotificationServiceMock;
  let matomoServiceMock: jasmine.SpyObj<MatomoService>;

  beforeEach(async () => {
    activatedRouteMock = { data: of({ result: 'test' }) };
    const apiProxyServiceMock = {
      conversationUrl: '/api/chat',
      deleteSessionUrl: '/api/session',
    };
    bedrockChatServiceMock = {
      chatMessages: [],
      notificationId: 'notif-1',
      focus$: new Subject(),
      isLoading$: new BehaviorSubject(false),
      chatMessage$: new Subject(),
      conversationId: 'convId',
      getChatMessageId: () => '123',
      setChatStreamResponse: jasmine.createSpy(),
    };
    feedbackServiceMock = jasmine.createSpyObj('FeedbackService', [
      'saveFeedback',
    ]);

    notificationServiceMock = {
      notifications: {
        subscribe: () => ({ unsubscribe: () => undefined }),
      },
      update: jasmine.createSpy('update'),
    };

    matomoServiceMock = jasmine.createSpyObj('MatomoService', ['trackEvent']);

    await TestBed.configureTestingModule({
      imports: [ChatbotComponent],
      providers: [
        {
          provide: ActivatedRoute,
          useValue: activatedRouteMock,
        },
        { provide: ApiProxyService, useValue: apiProxyServiceMock },
        {
          provide: BedrockChatService,
          useValue: bedrockChatServiceMock,
        },
        {
          provide: NotificationService,
          useValue: notificationServiceMock,
        },
        {
          provide: MatomoService,
          useValue: matomoServiceMock,
        },
        {
          provide: FeedbackService,
          useValue: feedbackServiceMock,
        },
        {
          provide: ENV_CONFIG,
          useValue: {
            apiEndpoint: '',
            userPoolId: '',
            userPoolClientId: '',
            region: '',
            redirectSigninUrl: '',
            redirectSignoutUrl: '',
            cognitoDomain: '',
            anonymousAccess: false,
            intern: true,
          },
        },
        provideHttpClient(),
      ],
    }).compileComponents();

    fixture = TestBed.createComponent(ChatbotComponent);
    component = fixture.componentInstance;
    fixture.detectChanges();
  });

  it('should create', () => {
    expect(component).toBeTruthy();
  });

  describe('lifecycle tests', () => {
    it('should initialize values on ngOnInit', () => {
      expect(component.chatMessages).toEqual([]);
    });
  });

  describe('textArea focus and scroll', () => {
    let focusBeenCalled = false;
    let scollIntoViewCalled = false;

    const textarea = {
      input: () => ({
        nativeElement: {
          focus: () => {
            focusBeenCalled = true;
          },
          scrollIntoView: () => {
            scollIntoViewCalled = true;
          },
        },
      }),
    } as TextareaComponent;

    beforeEach(() => {
      component.textArea = {
        first: textarea,
      } as QueryList<TextareaComponent>;
      focusBeenCalled = false;
      scollIntoViewCalled = false;
    });

    it('should focus on textarea in focusOnTextArea()', () => {
      component['focusOnTextArea']();
      expect(focusBeenCalled).toBeTrue();
    });

    it('should scroll and focus textarea in scrollOnTextArea()', () => {
      component['scrollOnTextArea']();
      expect(focusBeenCalled).toBeTrue();
      expect(scollIntoViewCalled).toBeTrue();
    });
  });

  describe('onSendMessage()', () => {
    it('should send message and clear input', () => {
      component.userInput = 'Hallo Welt';

      component.onSendMessage();

      expect(component.userInput).toBe('');
      expect(component.examplesVisible).toBeFalse();
      expect(bedrockChatServiceMock.setChatStreamResponse).toHaveBeenCalled();
    });

    it('should NOT send empty message', () => {
      component.userInput = '   ';

      component.onSendMessage();

      expect(
        bedrockChatServiceMock.setChatStreamResponse,
      ).not.toHaveBeenCalled();
    });
  });

  describe('onEnter()', () => {
    it('should call onSendMessage on Enter key', () => {
      spyOn(component, 'onSendMessage');

      component.userInput = 'hey!';
      const event = new Event('submit');

      component.onEnter(event);
      expect(component.onSendMessage).toHaveBeenCalled();
    });
  });

  describe('onExampleMsgClick', () => {
    it('should send example message on click', () => {
      spyOn(component, 'onSendMessage');

      component.onExampleMsgClick({
        item: { text: 'Beispiel' } as LinklistData,
        event: new MouseEvent('click'),
      });

      expect(component.userInput).toBe('Beispiel');
      expect(component.onSendMessage).toHaveBeenCalled();
    });
  });

  describe('isFeedbackProvidable()', () => {
    it('should detect providable feedback', () => {
      bedrockChatServiceMock.chatMessages.push(
        { role: 'user' },
        { role: 'assistant' },
      );

      expect(component.isFeedbackProvidable()).toBeTrue();
    });

    it('should deny feedback when already sent', () => {
      component['isFeedbackSent'] = true;
      expect(component.isFeedbackProvidable()).toBeFalse();
    });
  });

  describe('feedbackSent()', () => {
    it('should store feedback state on feedbackSent()', () => {
      component.feedbackPerTurn = { type: 'conversation' };
      component['feedbackSent'](true);
      expect(component['isFeedbackSent']).toBeTrue();
      expect(component.showPanel).toBeFalse();
    });
  });

  describe('feedback template bindings', () => {
    it('should call feedbackSent when FeedbackComponent emits submitted', () => {
      const feedbackSentSpy = spyOn(component, 'feedbackSent');
      component.showPanel = true;
      fixture.detectChanges();

      const feedbackDebugElement = fixture.debugElement.query(
        By.directive(FeedbackComponent),
      );
      expect(feedbackDebugElement).toBeTruthy();

      const feedbackChild =
        feedbackDebugElement.componentInstance as FeedbackComponent;
      feedbackChild.submitted.emit(true);

      expect(feedbackSentSpy).toHaveBeenCalledWith(true);
    });

    it('should call saveFeedback when FeedbackComponent emits feedbackSaved', () => {
      const saveFeedbackSpy = spyOn(component, 'saveFeedback');
      component.feedbackPerTurn = {
        messageId: 'message-1',
        type: 'perTurn',
      };
      component.showPanel = true;
      fixture.detectChanges();

      const feedbackDebugElement = fixture.debugElement.query(
        By.directive(FeedbackComponent),
      );
      expect(feedbackDebugElement).toBeTruthy();

      const feedbackChild =
        feedbackDebugElement.componentInstance as FeedbackComponent;
      const payload = {
        isMultiturn: false,
        isSingleturn: false,
        isFreeUserTest: false,
        isFinalFeedback: false,
      } as MessageFeedback;

      feedbackChild.feedbackSaved.emit(payload);

      expect(saveFeedbackSpy).toHaveBeenCalledWith(payload, 'message-1');
    });
  });

  describe('getLastAssistantMessageId()', () => {
    it('should return last assistant message ID', () => {
      bedrockChatServiceMock.chatMessages.push(
        { id: '1', role: 'assistant' },
        { id: '2', role: 'assistant' },
      );

      expect(component.getLastAssistantMessageId()).toBe('2');
    });

    it('should return empty string if no assistant message exists', () => {
      expect(component.getLastAssistantMessageId()).toBe('');
    });
  });

  describe('openFeedbackModal()', () => {
    it('should open feedback modal', () => {
      component.openFeedbackModal();
      expect(component.showPanel).toBeTrue();
    });

    it('should preserve feedback state when the panel is temporarily closed', () => {
      component.feedbackPerTurn = { type: 'perTurn' };
      component.openFeedbackModal();
      fixture.detectChanges();

      const previousFeedback = fixture.debugElement.query(
        By.directive(FeedbackComponent),
      ).componentInstance as FeedbackComponent;
      previousFeedback.form.patchValue({
        usedScenario: 2,
        technicalCorrectivity: 'Ja',
        comment: 'Teilweise ausgefüllt',
      });
      const previousForm = previousFeedback.form;

      component.closeDocument();
      fixture.detectChanges();
      expect(
        fixture.debugElement.query(By.directive(FeedbackComponent)),
      ).toBeTruthy();

      component.openFeedbackModal();
      fixture.detectChanges();
      const newFeedback = fixture.debugElement.query(
        By.directive(FeedbackComponent),
      ).componentInstance as FeedbackComponent;
      expect(newFeedback).toBe(previousFeedback);
      expect(newFeedback.form).toBe(previousForm);
      expect(newFeedback.form.getRawValue()).toEqual(
        jasmine.objectContaining({
          usedScenario: 2,
          technicalCorrectivity: 'Ja',
          comment: 'Teilweise ausgefüllt',
        }),
      );
    });

    it('should reset feedback state when the feedback type changes', () => {
      component.feedbackPerTurn = { type: 'perTurn' };
      component.openFeedbackModal();
      fixture.detectChanges();

      const feedback = fixture.debugElement.query(
        By.directive(FeedbackComponent),
      ).componentInstance as FeedbackComponent;
      feedback.form.patchValue({ comment: 'Teilweise ausgefüllt' });
      const previousForm = feedback.form;

      component.closeDocument();
      fixture.detectChanges();
      component.feedbackPerTurn = { type: 'conversation' };
      component.openFeedbackModal();
      fixture.detectChanges();

      expect(feedback.form).not.toBe(previousForm);
      expect(feedback.rawFeedbackRating.isPerTurnFeedback).toBeFalse();
    });
  });

  describe('randomQuestions()', () => {
    it('shoud choose 4 random example questions', () => {
      expect(component.randomQuestions().length).toBe(4);
    });

    it('shoud display one rente, one reha, one versicherung and one one sonstiges question', () => {
      const result: ExampleQuestionLinklistData[] = component.randomQuestions();

      expect(
        result.filter(
          (entry) => entry.category === ExampleQuestionCategory.Rente,
        ).length,
      ).toBe(1);
      expect(
        result.filter(
          (entry) => entry.category === ExampleQuestionCategory.Reha,
        ).length,
      ).toBe(1);
      expect(
        result.filter(
          (entry) => entry.category === ExampleQuestionCategory.Sonstiges,
        ).length,
      ).toBe(1);
      expect(
        result.filter(
          (entry) => entry.category === ExampleQuestionCategory.Versicherung,
        ).length,
      ).toBe(1);
    });
  });
  describe('saveFeedback()', () => {
    it('should NOT call service and has alert notification if IDs missing', () => {
      component['getLastAssistantMessageId'] = () => {
        return '';
      };
      const notification = feedbackErrorNotification;
      component['saveFeedback']({
        isMultiturn: false,
        isSingleturn: false,
        isFreeUserTest: false,
        isFinalFeedback: false,
      } as MessageFeedback);

      expect(notificationServiceMock.update).toHaveBeenCalledTimes(1);
      expect(notificationServiceMock.update).toHaveBeenCalledWith(notification);
      expect(feedbackServiceMock.saveFeedback).not.toHaveBeenCalled();
    });

    it('should send feedback, close modal on success', () => {
      component.feedbackPerTurn = { type: 'conversation' };
      component['getLastAssistantMessageId'] = () => {
        return 'msgId';
      };
      feedbackServiceMock.saveFeedback.and.returnValue(of({ success: true }));

      component['saveFeedback']({
        isMultiturn: false,
        isSingleturn: false,
        isFreeUserTest: false,
        isFinalFeedback: false,
      } as MessageFeedback);

      expect(feedbackServiceMock.saveFeedback).toHaveBeenCalled();
      expect(component.isFeedbackSent).toBeTruthy();
      expect(component.showPanel).toBeFalse();
    });

    it('should store the message ID after successful per-turn feedback', () => {
      component.feedbackPerTurn = {
        messageId: 'message-1',
        type: 'perTurn',
      };
      feedbackServiceMock.saveFeedback.and.returnValue(of({ success: true }));

      component['saveFeedback'](
        {
          isMultiturn: true,
          isSingleturn: false,
          isFreeUserTest: false,
          isFinalFeedback: false,
        } as MessageFeedback,
        'message-1',
      );

      expect(component.feedbackPerTurnMessageIds.has('message-1')).toBeTrue();
      expect(component.feedbackPerTurnMessageIds.has('message-2')).toBeFalse();
    });

    it('should emit alert notification and close modal on error', () => {
      const notification = feedbackErrorNotification;
      component['getLastAssistantMessageId'] = () => {
        return 'msgId';
      };
      feedbackServiceMock.saveFeedback.and.returnValue(
        throwError(() => new Error('fail')),
      );

      component['saveFeedback']({
        isMultiturn: false,
        isSingleturn: false,
        isFreeUserTest: false,
        isFinalFeedback: false,
      } as MessageFeedback);

      expect(component.isFeedbackSent).toBeFalsy();
      expect(notificationServiceMock.update).toHaveBeenCalledWith(notification);
    });

    it('should set helpfulness to GOOD, and call saveFeedback', () => {
      spyOn(component, 'saveFeedback');
      const feedback = { messageId: '123456', value: UserFeedback.Good };
      component.submitOnWasHelpful(feedback);

      expect(component.rawFeedbackRating.helpfulness).toEqual(
        UserFeedback.Good,
      );
      expect(component.saveFeedback).toHaveBeenCalledTimes(1);
    });

    it('should set helpfulness to BAD', () => {
      spyOn(component, 'saveFeedback');
      const feedback = { messageId: '123456', value: UserFeedback.Bad };
      component.submitOnWasHelpful(feedback);

      expect(component.rawFeedbackRating.helpfulness).toEqual(UserFeedback.Bad);
      expect(component.saveFeedback).toHaveBeenCalledTimes(1);
    });
  });

  describe('B3 — Button tracking', () => {
    it('should track Hilfe event on openHelpModal()', () => {
      component.openHelpModal();

      expect(matomoServiceMock.trackEvent).toHaveBeenCalledWith(
        'Chatbot',
        'Button',
        'Hilfe',
      );
    });

    it('should track Ihre-Meinung event on contact button click', () => {
      spyOn(window, 'open');
      component.buttons[0].buttonClick();

      expect(matomoServiceMock.trackEvent).toHaveBeenCalledWith(
        'Chatbot',
        'Button',
        'Ihre-Meinung',
      );
      expect(window.open).toHaveBeenCalledWith(
        'https://deutsche-rentenversicherung.de/renate-feedback',
        '_blank',
        jasmine.any(String),
      );
    });

    it('should track Drucken event on print button click', () => {
      spyOn(window, 'print');
      component.buttons[1].buttonClick();

      expect(matomoServiceMock.trackEvent).toHaveBeenCalledWith(
        'Chatbot',
        'Button',
        'Drucken',
      );
    });

    it('should track Einwilligung-widerrufen on doCancelSession()', () => {
      (
        bedrockChatServiceMock as unknown as { deleteSessionData: jasmine.Spy }
      ).deleteSessionData = jasmine
        .createSpy()
        .and.returnValue(of({ status: 'ok' }));

      spyOn(window, 'setTimeout').and.stub();
      component.doCancelSession();

      expect(matomoServiceMock.trackEvent).toHaveBeenCalledWith(
        'Chatbot',
        'Button',
        'Einwilligung-widerrufen',
      );
    });
  });

  describe('B5 — Erste-Eingabe', () => {
    it('should track Freitext on first free-text input', () => {
      component.userInput = 'Was ist eine Witwenrente?';

      component.onSendMessage();

      expect(matomoServiceMock.trackEvent).toHaveBeenCalledWith(
        'Chatbot',
        'Erste-Eingabe',
        'Freitext',
      );
    });

    it('should track Beispielfrage on first example click', () => {
      const onSendMessageSpy = spyOn(
        component,
        'onSendMessage',
      ).and.callThrough();

      component.onExampleMsgClick({
        item: { text: 'Beispiel' } as LinklistData,
        event: new MouseEvent('click'),
      });

      expect(onSendMessageSpy).toHaveBeenCalledWith('Beispielfrage');
      expect(matomoServiceMock.trackEvent).toHaveBeenCalledWith(
        'Chatbot',
        'Erste-Eingabe',
        'Beispielfrage',
      );
    });

    it('should NOT track Erste-Eingabe when the conversation already has a user message', () => {
      bedrockChatServiceMock.chatMessages.push({
        id: 'existing-user-message',
        role: 'user',
      });
      component.userInput = 'Zweite Frage';

      component.onSendMessage();

      expect(matomoServiceMock.trackEvent).not.toHaveBeenCalledWith(
        'Chatbot',
        'Erste-Eingabe',
        jasmine.any(String),
      );
    });

    it('should allow a new first-input event after clearConversation()', () => {
      component.userInput = 'Erste Frage';
      component.onSendMessage();
      bedrockChatServiceMock.chatMessages.push({
        id: 'existing-user-message',
        role: 'user',
      });
      matomoServiceMock.trackEvent.calls.reset();

      (
        bedrockChatServiceMock as unknown as { clearConversation: () => void }
      ).clearConversation = () => {
        bedrockChatServiceMock.chatMessages.length = 0;
      };

      component.startNewConversation();

      component.userInput = 'Neue erste Frage';
      component.onSendMessage();

      expect(matomoServiceMock.trackEvent).toHaveBeenCalledWith(
        'Chatbot',
        'Erste-Eingabe',
        'Freitext',
      );
    });
  });

  describe('B6 — Weiterleitung-angezeigt', () => {
    it('should track Weiterleitung-angezeigt when bot response contains referral link', () => {
      (bedrockChatServiceMock.chatMessage$ as Subject<unknown>).next({
        role: 'assistant',
        content:
          '[Rentenrechner](https://example.com/rentenbeginn-und-rentenhoehe)',
      });

      expect(matomoServiceMock.trackEvent).toHaveBeenCalledWith(
        'Chatbot',
        'Weiterleitung-angezeigt',
        'Rentenrechner',
      );
    });

    it('should NOT track Weiterleitung-angezeigt for user messages', () => {
      (bedrockChatServiceMock.chatMessage$ as Subject<unknown>).next({
        role: 'user',
        content: '[Rentenrechner](https://example.com/rentenrechner)',
      });

      expect(matomoServiceMock.trackEvent).not.toHaveBeenCalledWith(
        'Chatbot',
        'Weiterleitung-angezeigt',
        jasmine.any(String),
      );
    });

    it('should NOT track Weiterleitung-angezeigt for the welcome message', () => {
      (bedrockChatServiceMock.chatMessage$ as Subject<unknown>).next({
        role: 'assistant',
        content:
          'Mein Wissen basiert auf der <a href="https://www.deutsche-rentenversicherung.de/DRV/DE/Ueber-uns-und-Presse/Mediathek/Broschueren/broschueren_node.html">Gemeinsamen Broschürenreihe</a>. ' +
          'Bitte teilen Sie <a href="https://www.deutsche-rentenversicherung.de/DRV/DE/Service/Footer/Datenschutz/datenschutz_node.html">keine personenbezogenen Daten</a> mit mir.',
      });

      expect(matomoServiceMock.trackEvent).not.toHaveBeenCalledWith(
        'Chatbot',
        'Weiterleitung-angezeigt',
        jasmine.any(String),
      );
    });
  });
});
