import {
  HttpErrorResponse,
  provideHttpClient,
  withInterceptors,
} from '@angular/common/http';
import {
  HttpTestingController,
  provideHttpClientTesting,
} from '@angular/common/http/testing';
import { fakeAsync, TestBed, tick } from '@angular/core/testing';
import { DomSanitizer, SafeHtml } from '@angular/platform-browser';
import { NotificationService } from '@drv-ds/drv-design-system-ng';
import {
  ChatMessage,
  ChatOutput,
  Message,
  MessageChunk,
} from '@models/bedrock-chat.models';
import { welcomeMessage } from '@models/messages/messages.models';
import { ApiProxyService } from '@services/api-proxy/api-proxy.service';
import { BedrockChatService } from './bedrock-chat.service';
import { SessionService } from '@services/session.service';
import { LocalNotification } from '@components/feedback/feedback.component';
import { retryInterceptor } from 'src/app/interceptors/retry.interceptor';
import { marked } from 'marked';

describe('BedrockChatService', () => {
  let service: BedrockChatService;
  interface BedrockChatServicePrivate {
    chatMessages: ChatMessage[];
    processMarkdown: (text: string) => Promise<string | SafeHtml>;
    processMessageResponse: (
      messageData: {
        messageId: string;
        content: { contentType: string; body: string }[];
      },
      relatedDocs: MessageChunk[],
    ) => Promise<{
      id: string;
      relatedDocuments: MessageChunk[];
    }>;
    composeUsedChanksFromSameBrochure: (
      doc: MessageChunk,
      unicDocs: MessageChunk[],
    ) => MessageChunk[];
    cleanRelatedDocuments: (relatedDocs: MessageChunk[]) => MessageChunk[];
    adjustmentTableHeader: (input: string) => string;
    getChatMessageId: () => number | string;
    addErrorChatMessage: (notification: LocalNotification) => Promise<void>;
  }
  let servicePrivate: BedrockChatServicePrivate;
  let sanitizer: DomSanitizer;
  let sessionServiceMock: jasmine.SpyObj<SessionService>;
  let httpMock: HttpTestingController;

  const apiProxyServiceMock = {
    conversationUrl: 'http://mock-api.conversation/api/chat',
    deleteSessionUrl: 'http://mock-api.delete-session',
  };

  const notificationServiceMock = {};

  beforeEach(() => {
    sessionServiceMock = jasmine.createSpyObj('SessionService', [
      'getSessionId',
      'hadExistingSession',
    ]);
    TestBed.configureTestingModule({
      providers: [
        BedrockChatService,
        provideHttpClient(withInterceptors([retryInterceptor])),
        provideHttpClientTesting(),
        { provide: ApiProxyService, useValue: apiProxyServiceMock },
        { provide: NotificationService, useValue: notificationServiceMock },
        { provide: SessionService, useValue: sessionServiceMock },
      ],
    });

    service = TestBed.inject(BedrockChatService);
    servicePrivate = service as unknown as BedrockChatServicePrivate;
    httpMock = TestBed.inject(HttpTestingController);
    sanitizer = TestBed.inject(DomSanitizer);

    spyOn(sanitizer, 'bypassSecurityTrustHtml').and.callFake(
      (html: string) => html as unknown as SafeHtml,
    );
  });

  afterEach(() => {
    httpMock.verify();
  });

  it('should be created', () => {
    expect(service).toBeTruthy();
  });

  describe('initialize()', () => {
    it('should add welcome message when chatMessages is empty', async () => {
      service.chatMessages = [];

      await service.initialize();

      expect(service.chatMessages.length).toBe(1);
    });

    it('should not add duplicate welcome message when called multiple times', async () => {
      service.chatMessages = [];

      await service.initialize();
      await service.initialize();

      expect(service.chatMessages.length).toBe(1);
    });

    it('should not add welcome message when chatMessages already has entries', async () => {
      service.chatMessages = [
        { content: 'existing' } as unknown as ChatMessage,
      ];

      await service.initialize();

      expect(service.chatMessages.length).toBe(1);
    });
  });

  describe('addWelcomeMessage()', () => {
    const initMessage: ChatMessage = {
      id: '',
      role: 'assistant',
      content: welcomeMessage,
    };

    it('should have welcome message after initialisation', async () => {
      spyOn(service, 'addWelcomeMessage').and.callFake(async () => {
        service.chatMessages.push(initMessage);
      });
      //when
      service.initialize();
      //then
      expect(service.chatMessages.length).toBe(1);
      expect(service.chatMessages[0].content).toBe(initMessage.content);
    });

    it('should add welcome message after method call', async () => {
      service.chatMessages = []; // "reset" the chatmessages

      expect(service.chatMessages.length).toBeLessThan(1);

      await service.addWelcomeMessage();

      expect(service.chatMessages.length).toBe(1);
      expect(service.chatMessages[0].content).toBe(initMessage.content);
    });
  });

  describe('getChatMessageId()', () => {
    it('should return an empty string if no messages', () => {
      expect(service.getChatMessageId()).toBe('');
    });

    it('should return parent messageId if there is one message', () => {
      const parentId = 'parentId';

      service.messages.push({
        parent: parentId,
      } as Message);

      expect(service.getChatMessageId()).toBe(parentId);
    });

    it('should return last parent messageId if there are messages', () => {
      const firstParentId = 'firstParentId';
      const lastParentId = 'lastParentId';

      service.messages.push({
        parent: firstParentId,
      } as Message);

      service.messages.push({
        parent: lastParentId,
      } as Message);

      expect(service.getChatMessageId()).toBe(lastParentId);
    });
  });

  describe('updateIds()', () => {
    it('should update conversationId', () => {
      //given
      const newConversationId = 'newConversationId';
      sessionServiceMock.getSessionId.and.returnValue(newConversationId);

      expect(service.conversationId).toBe(newConversationId);
      expect(sessionServiceMock.getSessionId).toHaveBeenCalled();
    });
  });

  describe('postChatMessage()', () => {
    const message = 'message';
    const conversationId = 'conversationId';

    it('should call the correct URL with POST and send ChatMessage', () => {
      sessionServiceMock.getSessionId.and.returnValue(conversationId);
      const chatOutPut: ChatOutput = {} as ChatOutput;
      //when
      service.postChatMessage(message).subscribe((response) => {
        expect(response).toEqual(chatOutPut);
      });

      const req = httpMock.expectOne(apiProxyServiceMock.conversationUrl);
      const messageId = req.request.body.message.messageId.split('#')[1];

      expect(messageId).toMatch(
        /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i,
      );
      expect(req.request.method).toBe('POST');
      expect(req.request.body.message.content[0].body).toEqual(message);
      expect(req.request.body.conversationId).toBe(conversationId);
      expect(req.request.headers.get('Content-Type')).toBe('application/json');

      req.flush(chatOutPut);
    });

    it('should return 502 after retries are exhausted', fakeAsync(() => {
      let actualError: HttpErrorResponse | undefined;

      service.postChatMessage('hello').subscribe({
        error: (err) => (actualError = err),
      });

      httpMock
        .expectOne(apiProxyServiceMock.conversationUrl)
        .flush('Bad Gateway', {
          status: 502,
          statusText: 'Bad Gateway',
        });

      tick(1000);

      httpMock
        .expectOne(apiProxyServiceMock.conversationUrl)
        .flush('Bad Gateway', {
          status: 502,
          statusText: 'Bad Gateway',
        });

      tick(2000);

      httpMock
        .expectOne(apiProxyServiceMock.conversationUrl)
        .flush('Bad Gateway', {
          status: 502,
          statusText: 'Bad Gateway',
        });

      tick(4000);

      httpMock
        .expectOne(apiProxyServiceMock.conversationUrl)
        .flush('Bad Gateway', {
          status: 502,
          statusText: 'Bad Gateway',
        });

      expect(actualError?.status).toBe(502);
    }));

    it('should not retry 400 error', () => {
      let actualError: HttpErrorResponse | undefined;
      service.postChatMessage('hello').subscribe({
        error: (err) => (actualError = err),
      });

      httpMock
        .expectOne(service['apiProxy'].conversationUrl)
        .flush('Bad Request', {
          status: 400,
          statusText: 'Bad Request',
        });

      expect(actualError?.status).toBe(400);
      httpMock.expectNone(service['apiProxy'].conversationUrl);
    });
  });

  describe('extractSourceReferences()', () => {
    it('should find all matches with primary format and extract the capture group', () => {
      const text = `foo [^tooluse_abc123@123] [tooluse_abc123@123]
        bar ^tooluse_abc123@123
        baz [^tooluse_abc123@abc] [^tooluse_abc123@123]
        SOURCE_LINK_123456
        bam [^tooluse_abc123 ^tooluse_a@]
        crash [^tooluse_def456@456]
        `;

      const result = service['extractSourceReferences'](text);
      const expection = ['123', '456'];

      expect(result).toEqual(expection);
    });

    it('should find no matches with primary format and extract the capture group', () => {
      const text = `foo [tooluse_abc123123]
        bar ^tooluse_abc123@123
        SOURCE_LINK_123456
        baz [^tooluse_abc123@abc]
        SOURCE_LINK_789
        SOURCE_LINK_TO_THE_PAST
        SOURCE_LINK_123456
        bam [^tooluse_abc123 ^tooluse_a@]
        `;

      const result = service['extractSourceReferences'](text);
      const expection = ['source_123456', 'source_789'];

      expect(result).toEqual(expection);
    });
  });

  describe('processMarkdown()', () => {
    it('should strip citation references [N] from text', async () => {
      const text = `Lorem ipsum [1] and [2] more text`;

      const markedHtml = await service['processMarkdown'](text);

      expect(markedHtml as string).not.toContain('[1]');
      expect(markedHtml as string).not.toContain('[2]');
    });

    it('should convert markdown to HTML and sanitize it', async () => {
      const input = 'Hello **World**';

      const result = await service['processMarkdown'](input);

      expect(sanitizer.bypassSecurityTrustHtml).toHaveBeenCalled();
      expect(result as string).toContain('<strong>World</strong>');
    });

    it('should bold numbered section titles', async () => {
      const input = '1. This is a section';

      const result = await service['processMarkdown'](input);

      expect(result as string).toContain('<ol>');
      expect(result as string).toContain('<li>This is a section</li>');
    });

    it('should strip citation [1] from text', async () => {
      const input = 'This is text [1] with source';

      const result = await service['processMarkdown'](input);

      expect(result as string).not.toContain('[1]');
    });

    it('should return SafeHtml', async () => {
      const input = 'Just text';

      const result = await service['processMarkdown'](input);

      expect(result).toBeDefined();
      expect(sanitizer.bypassSecurityTrustHtml).toHaveBeenCalledTimes(1);
    });

    it('should strip tool-use footnote references like [^tooluse_abc@123]', async () => {
      const input =
        'Some text [^tooluse_abc@123] and [^tooluse_xyz@456]:1 more text';

      const result = await service['processMarkdown'](input);

      expect(result as string).not.toContain('[^tooluse_abc@123]');
      expect(result as string).not.toContain('[^tooluse_xyz@456]');
    });

    it('should remove SOURCE_LINK references', async () => {
      const input = 'Text with SOURCE_LINK_123 and SOURCE_LINK_456 in it';

      const result = await service['processMarkdown'](input);

      expect(result as string).not.toContain('SOURCE_LINK_123');
      expect(result as string).not.toContain('SOURCE_LINK_456');
    });
  });

  describe('processMessageResponse', () => {
    beforeEach(() => {
      // mock dependencies used inside the private method

      spyOn(servicePrivate, 'processMarkdown').and.returnValue(
        Promise.resolve('<p>HTML</p>'),
      );
    });

    it('should strip <thinking> blocks, remove Quellen, prefix Hello, and return final object', async () => {
      const messageData = {
        messageId: '123',
        content: [
          {
            contentType: 'text',
            body: 'Some text <thinking>secret</thinking>',
          },
          { contentType: 'text', body: ' More text' },
        ],
      };

      const relatedDocs = [{ sourceName: 'Doc' } as MessageChunk];
      const result = await servicePrivate.processMessageResponse(
        messageData,
        relatedDocs,
      );

      expect(result.id).toBe('123');
      expect(result.relatedDocuments.length).toBe(1);
    });

    it('should compose relatedDocuments from the same brochure', async () => {
      const relatedDocs = [
        {
          sourceName: 'Doc',
          content: '1 content',
          brochureNumber: '11',
        } as MessageChunk,
        {
          sourceName: 'one more Doc',
          content: '2 another one',
          brochureNumber: '11',
        } as MessageChunk,
        {
          sourceName: 'another one Doc',
          content: 'content',
          brochureNumber: '12',
        } as MessageChunk,
      ];
      const fakeReturn = [
        {
          sourceName: 'Doc one more Doc',
          content: '1 content',
          brochureNumber: '11',
        } as MessageChunk,
        {
          sourceName: 'another one Doc',
          content: 'content',
          brochureNumber: '12',
        } as MessageChunk,
      ];

      const fakeSpy = spyOn(
        servicePrivate,
        'composeUsedChanksFromSameBrochure',
      ).and.callFake((doc: MessageChunk, unicDocs: MessageChunk[]) => {
        expect(doc).toBeDefined();
        expect(unicDocs.length).toBeGreaterThan(0);

        return fakeReturn;
      });

      const result: MessageChunk[] =
        servicePrivate.cleanRelatedDocuments(relatedDocs);
      expect(fakeSpy).toHaveBeenCalledTimes(3);
      expect(result).toEqual(fakeReturn);
    });

    it('should list a document once when one of its chunks lost its metadata (#676)', () => {
      const stem = '402_Kindererziehung_DE_20-Aufl_2026-04_digibro';
      const relatedDocs = [
        {
          documentId: stem,
          sourceName: 'Kindererziehung: Ihr Plus für die Rente',
          content: 'resolved chunk',
          brochureNumber: 'F01',
          sourceIndex: 1,
        } as MessageChunk,
        {
          // Same documentId, but metadata failed to resolve on this chunk.
          documentId: stem,
          sourceName: `${stem}_0000.md`,
          content: 'unresolved chunk',
          sourceIndex: 2,
        } as MessageChunk,
      ];

      const result: MessageChunk[] =
        servicePrivate.cleanRelatedDocuments(relatedDocs);

      expect(result.length).toBe(1);
      expect(result[0].sourceName).toBe(
        'Kindererziehung: Ihr Plus für die Rente',
      );
    });

    it('should adopt the resolved title even when the unresolved chunk ranks first (#676)', () => {
      const stem = '402_Kindererziehung_DE_20-Aufl_2026-04';
      const relatedDocs = [
        {
          documentId: stem,
          sourceName: `${stem}_0000.md`,
          content: 'unresolved chunk',
          sourceIndex: 1,
        } as MessageChunk,
        {
          documentId: stem,
          sourceName: 'Kindererziehung',
          content: 'resolved chunk',
          brochureNumber: 'F01',
          publishingDate: '4/2026',
          sourceIndex: 2,
        } as MessageChunk,
      ];

      const result: MessageChunk[] =
        servicePrivate.cleanRelatedDocuments(relatedDocs);

      expect(result.length).toBe(1);
      expect(result[0].sourceName).toBe(
        'Kindererziehung',
      );
      expect(result[0].brochureNumber).toBe('F01');
      expect(result[0].publishingDate).toBe('4/2026');
    });

    it('should collapse an extracted table chunk onto its parent brochure (#676)', () => {
      const relatedDocs = [
        {
          sourceName: 'Mit Rehabilitation wieder fit für den Job',
          content: 'main chunk',
          brochureNumber: 'B15',
          sourceIndex: 1,
        } as MessageChunk,
        {
          sourceName: 'Mit Rehabilitation wieder fit für den Job',
          content: 'table chunk',
          brochureNumber: 'B15',
          sourceIndex: 2,
        } as MessageChunk,
      ];

      const result: MessageChunk[] =
        servicePrivate.cleanRelatedDocuments(relatedDocs);

      expect(result.length).toBe(1);
    });

    it('should keep distinct documents apart when both lost their metadata (#676)', () => {
      const relatedDocs = [
        {
          sourceName: '402_Kindererziehung_0000.md',
          content: 'a',
          sourceIndex: 1,
        } as MessageChunk,
        {
          sourceName: '503_Arbeitslos_0003.md',
          content: 'b',
          sourceIndex: 2,
        } as MessageChunk,
      ];

      const result: MessageChunk[] =
        servicePrivate.cleanRelatedDocuments(relatedDocs);

      expect(result.length).toBe(2);
    });

    it('should never render a chunk filename as a source label (#676)', () => {
      const relatedDocs = [
        {
          sourceName: 'R0815_0009.md',
          content: 'c',
          sourceIndex: 1,
        } as MessageChunk,
      ];

      const result: MessageChunk[] =
        servicePrivate.cleanRelatedDocuments(relatedDocs);

      expect(result[0].sourceName).not.toContain('.md');
      expect(result[0].sourceName).not.toContain('_0009');
    });

    it('should keep a GFM table renderable as a table', () => {
      const table = [
        '| Beginn der Rente wegen Erwerbsminderung Jahr | frühestmöglicher Rentenbeginn ohne Abschläge ab Jahre | frühestmöglicher Rentenbeginn ohne Abschläge ab Monate | vorzeitiger Rentenbeginn mit Höchstabschlag bis Jahre | vorzeitiger Rentenbeginn mit Höchstabschlag bis Monate |',
        '| --- | --- | --- | --- | --- |',
        '| 2019 | 64 | 2 | 61 | 2 |',
        '| 2024 | 65 | 0 | 62 | 0 |',
      ].join('\n');

      const result: MessageChunk[] = servicePrivate.cleanRelatedDocuments([
        {
          sourceName: 'Erwerbsminderungsrente',
          content: table,
          sourceIndex: 1,
        } as MessageChunk,
      ]);

      const html = marked.parse(result[0].content) as string;

      expect(html).toContain('<table>');
      expect((html.match(/<th>/g) ?? []).length).toBe(5);
      expect(html).not.toContain('<hr>');
      expect(html).toContain('<td>2024</td>');
    });

    it('should still strip the leftover "**↓**" marker', () => {
      const result: MessageChunk[] = servicePrivate.cleanRelatedDocuments([
        {
          sourceName: 'Erwerbsminderungsrente',
          content: 'Vorher **↓** nachher',
          sourceIndex: 1,
        } as MessageChunk,
      ]);

      expect(result[0].content).toBe('Vorher  nachher');
    });

    it('should repair a table with an empty header row end to end', () => {
      const table = ['|   |   |', '|---|---|', '| A | B |'].join('\n');

      const result: MessageChunk[] = servicePrivate.cleanRelatedDocuments([
        {
          sourceName: 'Erwerbsminderungsrente',
          content: table,
          sourceIndex: 1,
        } as MessageChunk,
      ]);

      const html = marked.parse(result[0].content) as string;

      expect(html).toContain('<th>A</th>');
      expect(html).toContain('<th>B</th>');
    });

    it('should remove empty header row and keep separator', () => {
      const input = `
|   |   |
|---|---|
| A | B |
`.trim();

      const expected = `
| A | B |
|---|---|
`.trim();

      const result = servicePrivate.adjustmentTableHeader(input);

      expect(result).toBe(expected);
    });

    it('should handle multiple lines and a single separator correctly', () => {
      const input = `
|   |   |
|---|---|
| A | B |
| C | D |
`.trim();

      const expected = `
| A | B |
|---|---|
| C | D |
`.trim();

      const result = servicePrivate.adjustmentTableHeader(input);

      expect(result).toBe(expected);
    });

    it('should keep the separator of an already well-formed table', () => {
      const input = `
| Voraussetzungen | Regelaltersrente | langjährig Versicherte |
| --- | --- | --- |
| Mindestalter | 65 | 63 |
`.trim();

      const result = servicePrivate.adjustmentTableHeader(input);

      expect(result).toBe(input);
    });

    it('should not emit two separators when a relocated one meets an existing separator', () => {
      const input = `
|   |   |
|---|---|
| A | B |
|---|---|
| C | D |
`.trim();

      const expected = `
| A | B |
|---|---|
| C | D |
`.trim();

      const result = servicePrivate.adjustmentTableHeader(input);

      expect(result).toBe(expected);
    });
  });

  describe('Behavioral scenarios: postChatMessage pipeline', () => {
    const message = 'Test message';
    const conversationId = 'test-session';
    const mockResponse: ChatOutput = {
      conversationId: 'test-session',
      message: {
        role: 'assistant',
        parent: 'msg-1',
        messageId: 'msg-1',
        content: [{ contentType: 'text', body: 'Answer' }],
      },
    } as ChatOutput;

    beforeEach(() => {
      sessionServiceMock.getSessionId.and.returnValue(conversationId);
    });
    it('should return response', () => {
      let result: ChatOutput | undefined;

      service.postChatMessage(message).subscribe({
        next: (r) => (result = r),
        error: () => fail('Should not error'),
      });

      const req = httpMock.expectOne(apiProxyServiceMock.conversationUrl);
      req.flush(mockResponse);

      expect(result).toEqual(mockResponse);
    });

    it('should add error message when notification contains text', async () => {
      const notification = { text: 'Test error' } as LocalNotification;
      spyOn(servicePrivate, 'getChatMessageId').and.returnValue(1);
      await servicePrivate.addErrorChatMessage(notification);
      expect(servicePrivate.chatMessages.length).toBe(1);
    });
  });
  describe('deleteSessionData()', () => {
    const sessionId = 'test-session-id';
    beforeEach(() => {
      sessionServiceMock.getSessionId.and.returnValue(sessionId);
    });
    it('should call delete endpoint with current session id', () => {
      const mockResponse = { status: 'success' };
      service.deleteSessionData().subscribe((response) => {
        expect(response).toEqual(mockResponse);
      });
      const req = httpMock.expectOne(
        `${apiProxyServiceMock.deleteSessionUrl}/${sessionId}`,
      );
      expect(req.request.method).toBe('DELETE');
      req.flush(mockResponse);
    });
    it('should use session id from SessionService', () => {
      service.deleteSessionData().subscribe();
      const req = httpMock.expectOne(
        `${apiProxyServiceMock.deleteSessionUrl}/${sessionId}`,
      );
      expect(sessionServiceMock.getSessionId).toHaveBeenCalled();
      req.flush({ status: 'success' });
    });
  });
});
