import { ComponentFixture, TestBed } from '@angular/core/testing';
import { ChatMessage, ChatSource } from '@models/bedrock-chat.models';
import { ChatMessageService } from '@services/chat-message.service';
import { PrintableChatMessageComponent } from './printable-chat-message.component';

describe('PrintableChatMessageComponent', () => {
  let component: PrintableChatMessageComponent;
  let fixture: ComponentFixture<PrintableChatMessageComponent>;
  let chatMessageServiceSpy: jasmine.SpyObj<ChatMessageService>;

  beforeEach(async () => {
    chatMessageServiceSpy = jasmine.createSpyObj('ChatMessageService', [
      'convertToHtml',
      'extractSources',
    ]);

    await TestBed.configureTestingModule({
      imports: [PrintableChatMessageComponent],
      providers: [
        { provide: ChatMessageService, useValue: chatMessageServiceSpy },
      ],
    }).compileComponents();

    fixture = TestBed.createComponent(PrintableChatMessageComponent);
    component = fixture.componentInstance;
  });

  const mockMessage: ChatMessage = {
    id: 'id',
    role: 'assistant',
    content: 'Hello World',
  };

  it('should create', () => {
    expect(component).toBeTruthy();
  });

  describe('getSources()', () => {
    it('should call extractSources only once and cache the result', () => {
      const sampleSources = [{} as ChatSource];
      chatMessageServiceSpy.extractSources.and.returnValue(sampleSources);

      component.message = mockMessage;

      const result1 = component.getSources();
      const result2 = component.getSources();

      expect(result1).toEqual(sampleSources);
      expect(result2).toEqual(sampleSources);

      expect(chatMessageServiceSpy.extractSources).toHaveBeenCalledTimes(1);
      expect(chatMessageServiceSpy.extractSources).toHaveBeenCalledWith(
        'Hello World',
      );
    });

    it('should return an empty array if message has no content', () => {
      component.message = { ...mockMessage, content: '' };

      const result = component.getSources();

      expect(result).toEqual([]);
      expect(chatMessageServiceSpy.extractSources).not.toHaveBeenCalled();
    });
  });
});
