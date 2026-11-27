import { provideHttpClient } from '@angular/common/http';
import {
  HttpTestingController,
  provideHttpClientTesting,
} from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { ApiProxyService } from '@services/api-proxy/api-proxy.service';
import { FeedbackService } from './feedback.service';
import { MessageFeedback } from '@models/bedrock-chat.models';

describe('FeedbackService', () => {
  let service: FeedbackService;

  let httpMock: HttpTestingController;

  const apiProxyServiceMock = {
    conversationUrl: 'http://mock-api.local',
  };

  beforeEach(() => {
    TestBed.configureTestingModule({
      providers: [
        FeedbackService,
        provideHttpClient(),
        provideHttpClientTesting(),
        { provide: ApiProxyService, useValue: apiProxyServiceMock },
      ],
    });
    service = TestBed.inject(FeedbackService);
    httpMock = TestBed.inject(HttpTestingController);
  });

  afterEach(() => {
    httpMock.verify();
  });

  it('should be created', () => {
    expect(service).toBeTruthy();
  });

  it('should call the correct URL with PUT and send feedback data', () => {
    const feedback: MessageFeedback = {
      comment: 'test',
      isFinalFeedback: false,
      isFreeUserTest: false,
      isMultiturn: false,
      isSingleturn: false,
      helpfulness: null,
    } as MessageFeedback;
    const sessionId = 'conv123';

    service
      .saveFeedback(feedback, sessionId, 'msg-123')
      .subscribe((response) => {
        expect(response).toEqual({ success: true });
      });

    const req = httpMock.expectOne('http://mock-api.local/conv123/feedback');

    expect(req.request.method).toBe('PUT');
    expect(req.request.body).toEqual({ messageId: 'msg-123', ...feedback });
    expect(req.request.headers.get('Content-Type')).toBe('application/json');

    // Simuliere Backend-Response
    req.flush({ success: true });
  });

  it('should handle error responses from the server', () => {
    const feedback: MessageFeedback = {} as MessageFeedback;

    service.saveFeedback(feedback, 'conv999', 'msg-456').subscribe({
      next: () => fail('Expected an error, not success'),
      error: (error) => {
        expect(error.status).toBe(500);
      },
    });

    const req = httpMock.expectOne('http://mock-api.local/conv999/feedback');

    req.flush('Server error', {
      status: 500,
      statusText: 'Internal Server Error',
    });
  });
});
