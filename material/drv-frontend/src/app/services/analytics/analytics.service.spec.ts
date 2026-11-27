import { provideHttpClient } from '@angular/common/http';
import {
  HttpTestingController,
  provideHttpClientTesting,
} from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { ApiProxyService } from '@services/api-proxy/api-proxy.service';
import { AnalyticsService } from './analytics.service';

describe('AnalyticsService', () => {
  let service: AnalyticsService;
  let httpMock: HttpTestingController;

  const apiProxyMock = { apiUrl: 'http://mock-api.local' };

  beforeEach(() => {
    TestBed.configureTestingModule({
      providers: [
        AnalyticsService,
        provideHttpClient(),
        provideHttpClientTesting(),
        { provide: ApiProxyService, useValue: apiProxyMock },
      ],
    });
    service = TestBed.inject(AnalyticsService);
    httpMock = TestBed.inject(HttpTestingController);
  });

  afterEach(() => httpMock.verify());

  it('should be created', () => {
    expect(service).toBeTruthy();
  });

  it('should call GET /api/analytics without params', () => {
    service.getAnalytics().subscribe();
    const req = httpMock.expectOne('http://mock-api.local/api/analytics');
    expect(req.request.method).toBe('GET');
    req.flush({
      totalSessions: 10,
      totalMessages: 50,
      avgMessagesPerSession: 5,
      topDomains: [],
      topSources: [],
      feedbackThumbsUpRate: null,
      blockedRate: 0,
    });
  });

  it('should append from_ts and to_ts when provided', () => {
    service.getAnalytics(1000, 2000).subscribe();
    const req = httpMock.expectOne(
      'http://mock-api.local/api/analytics?from_ts=1000&to_ts=2000',
    );
    expect(req.request.method).toBe('GET');
    req.flush({
      totalSessions: 0,
      totalMessages: 0,
      avgMessagesPerSession: 0,
      topDomains: [],
      topSources: [],
      feedbackThumbsUpRate: null,
      blockedRate: 0,
    });
  });
});
