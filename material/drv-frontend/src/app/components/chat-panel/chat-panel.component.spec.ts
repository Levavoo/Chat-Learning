import { ComponentFixture, TestBed } from '@angular/core/testing';
import { ChatMessage, MessageChunk } from '@models/bedrock-chat.models';
import { BedrockChatService } from '@services/bedrock-chat/bedrock-chat.service';
import { MatomoService } from '@services/matomo/matomo.service';
import { ChatPanelComponent } from './chat-panel.component';
import { UserFeedback } from '@models/feedback/feedback.model';

describe('ChatPanelComponent', () => {
  let fixture: ComponentFixture<ChatPanelComponent>;
  let component: ChatPanelComponent;

  let bedrockChatServiceMock: jasmine.SpyObj<BedrockChatService>;
  let matomoServiceMock: jasmine.SpyObj<MatomoService>;

  beforeEach(async () => {
    bedrockChatServiceMock = jasmine.createSpyObj('BedrockChatService', [], {
      chatMessages: [],
    });
    matomoServiceMock = jasmine.createSpyObj('MatomoService', ['trackEvent']);

    await TestBed.configureTestingModule({
      imports: [ChatPanelComponent],
      providers: [
        { provide: BedrockChatService, useValue: bedrockChatServiceMock },
        { provide: MatomoService, useValue: matomoServiceMock },
      ],
    }).compileComponents();

    fixture = TestBed.createComponent(ChatPanelComponent);
    component = fixture.componentInstance;

    fixture.detectChanges();
  });

  it('should create', () => {
    expect(component).toBeTruthy();
  });

  describe('lifecycle tests', () => {
    it('should set messageCount on ngAfterViewInit', () => {
      bedrockChatServiceMock.chatMessages.push(
        ...[{} as ChatMessage, {} as ChatMessage],
      );

      component.ngAfterViewInit();

      expect(component['messageCount']).toBe(2);
    });

    it('should detect new messages in ngAfterViewChecked', () => {
      component['messageCount'] = 1;
      bedrockChatServiceMock.chatMessages.push(
        ...[{} as ChatMessage, {} as ChatMessage, {} as ChatMessage],
      );

      component.ngAfterViewChecked();

      expect(component['messageCount']).toBe(3);
    });
  });

  describe('openDocument / closeDocument', () => {
    it('should open a document', () => {
      const doc = { sourceName: 'test' } as MessageChunk;

      component.openDocument(doc);

      expect(component.currentDocument).toBe(doc);
      expect(component.showPanel).toBeTrue();
    });

    it('should close the document', () => {
      component.showPanel = true;

      component.closeDocument();

      expect(component.showPanel).toBeFalse();
    });
  });

  describe('per-turn feedback', () => {
    it('should disable feedback only for submitted message IDs', () => {
      component.feedbackPerTurnMessageIds = new Set(['message-1']);

      expect(component.isPerTurnFeedbackDisabled('message-1')).toBeTrue();
      expect(component.isPerTurnFeedbackDisabled('message-2')).toBeFalse();
    });
  });

  describe('B1 — Quelle-angezeigt', () => {
    it('should track event with sourceName when openDocument is called', () => {
      const doc = {
        sourceName: 'Die Rente — Informationen für Frauen',
      } as MessageChunk;

      component.openDocument(doc);

      expect(matomoServiceMock.trackEvent).toHaveBeenCalledWith(
        'Chatbot',
        'Quelle-angezeigt',
        'Die Rente — Informationen für Frauen',
      );
    });

    it('should track "Unbekannt" when sourceName is missing', () => {
      const doc = {} as MessageChunk;

      component.openDocument(doc);

      expect(matomoServiceMock.trackEvent).toHaveBeenCalledWith(
        'Chatbot',
        'Quelle-angezeigt',
        'Unbekannt',
      );
    });
  });

  describe('B3 — Button (Feedback)', () => {
    it('should track Feedback-GOOD event', () => {
      const msg = { id: '123' } as ChatMessage;

      component.sendMessageFeedback(msg, UserFeedback.Good, 2);

      expect(matomoServiceMock.trackEvent).toHaveBeenCalledWith(
        'Chatbot',
        'Button',
        'Feedback-GOOD',
      );
    });

    it('should track Feedback-BAD event', () => {
      const msg = { id: '123' } as ChatMessage;

      component.sendMessageFeedback(msg, UserFeedback.Bad, 2);

      expect(matomoServiceMock.trackEvent).toHaveBeenCalledWith(
        'Chatbot',
        'Button',
        'Feedback-BAD',
      );
    });

    it('should track Feedback-NEUTRAL event', () => {
      const msg = { id: '123' } as ChatMessage;

      component.sendMessageFeedback(msg, UserFeedback.Neutral, 2);

      expect(matomoServiceMock.trackEvent).toHaveBeenCalledWith(
        'Chatbot',
        'Button',
        'Feedback-NEUTRAL',
      );
    });
  });

  describe('B4 — Welcome-Link', () => {
    it('should track Welcome-Link when clicking a link in the first bot message', () => {
      const chatMessage = document.createElement('drv-chat-message');
      chatMessage.setAttribute('data-message-index', '0');
      const anchor = document.createElement('a');
      anchor.href = 'https://example.com';
      anchor.textContent =
        'Gemeinsamen Broschürenreihe der Deutschen Rentenversicherung';
      chatMessage.appendChild(anchor);

      // Append to fixture element so closest() works
      fixture.nativeElement
        .querySelector('.drv-chat-panel')
        ?.appendChild(chatMessage);

      const event = new MouseEvent('click', { bubbles: true });
      Object.defineProperty(event, 'target', { value: anchor });

      component.onChatPanelClick(event);

      expect(matomoServiceMock.trackEvent).toHaveBeenCalledWith(
        'Chatbot',
        'Welcome-Link',
        'Gemeinsamen Broschürenreihe der Deutschen Rentenversicherung',
      );
    });

    it('should track Welcome-Link through the host click listener', () => {
      const chatMessage = document.createElement('drv-chat-message');
      chatMessage.setAttribute('data-message-index', '0');
      const anchor = document.createElement('a');
      anchor.textContent = 'Welcome-Link über HostListener';
      chatMessage.appendChild(anchor);
      fixture.nativeElement
        .querySelector('.drv-chat-panel')
        ?.appendChild(chatMessage);

      anchor.dispatchEvent(new MouseEvent('click', { bubbles: true }));

      expect(matomoServiceMock.trackEvent).toHaveBeenCalledWith(
        'Chatbot',
        'Welcome-Link',
        'Welcome-Link über HostListener',
      );
    });

    it('should track Welcome-Link for the Datenschutz link in the welcome bubble', () => {
      const chatMessage = document.createElement('drv-chat-message');
      chatMessage.setAttribute('data-message-index', '0');
      const anchor = document.createElement('a');
      anchor.href =
        'https://www.deutsche-rentenversicherung.de/DRV/DE/Service/Footer/Datenschutz/datenschutz_node.html';
      anchor.textContent = 'keine personenbezogenen Daten';
      chatMessage.appendChild(anchor);

      fixture.nativeElement
        .querySelector('.drv-chat-panel')
        ?.appendChild(chatMessage);

      const event = new MouseEvent('click', { bubbles: true });
      Object.defineProperty(event, 'target', { value: anchor });

      component.onChatPanelClick(event);

      expect(matomoServiceMock.trackEvent).toHaveBeenCalledWith(
        'Chatbot',
        'Welcome-Link',
        'keine personenbezogenen Daten',
      );
    });

    it('should NOT track Welcome-Link for clicks in non-first bot messages', () => {
      const chatMessage = document.createElement('drv-chat-message');
      chatMessage.setAttribute('data-message-index', '2');
      const anchor = document.createElement('a');
      anchor.href = 'https://example.com';
      anchor.textContent = 'Some link';
      chatMessage.appendChild(anchor);

      fixture.nativeElement
        .querySelector('.drv-chat-panel')
        ?.appendChild(chatMessage);

      const event = new MouseEvent('click', { bubbles: true });
      Object.defineProperty(event, 'target', { value: anchor });

      component.onChatPanelClick(event);

      expect(matomoServiceMock.trackEvent).not.toHaveBeenCalledWith(
        'Chatbot',
        'Welcome-Link',
        jasmine.any(String),
      );
    });
  });

  describe('B6 — Weiterleitung (click)', () => {
    it('should track Weiterleitung when clicking a referral link in a bot message', () => {
      const chatMessage = document.createElement('drv-chat-message');
      chatMessage.setAttribute('data-message-index', '2');
      const anchor = document.createElement('a');
      anchor.href = 'https://example.com/rentenbeginn-und-rentenhoehe';
      anchor.textContent = 'Rentenrechner';
      chatMessage.appendChild(anchor);

      fixture.nativeElement
        .querySelector('.drv-chat-panel')
        ?.appendChild(chatMessage);

      const event = new MouseEvent('click', { bubbles: true });
      Object.defineProperty(event, 'target', { value: anchor });

      component.onChatPanelClick(event);

      expect(matomoServiceMock.trackEvent).toHaveBeenCalledWith(
        'Chatbot',
        'Weiterleitung',
        'Rentenrechner',
      );
    });

    it('should NOT track Weiterleitung for non-referral link clicks', () => {
      const chatMessage = document.createElement('drv-chat-message');
      chatMessage.setAttribute('data-message-index', '2');
      const anchor = document.createElement('a');
      anchor.href = 'https://example.com/some-page';
      anchor.textContent = 'Some link';
      chatMessage.appendChild(anchor);

      fixture.nativeElement
        .querySelector('.drv-chat-panel')
        ?.appendChild(chatMessage);

      const event = new MouseEvent('click', { bubbles: true });
      Object.defineProperty(event, 'target', { value: anchor });

      component.onChatPanelClick(event);

      expect(matomoServiceMock.trackEvent).not.toHaveBeenCalled();
    });
  });
});
