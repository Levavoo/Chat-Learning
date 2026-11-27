import { TestBed, fakeAsync, tick } from '@angular/core/testing';
import {
  HttpClient,
  HttpErrorResponse,
  provideHttpClient,
  withInterceptors,
} from '@angular/common/http';
import {
  HttpTestingController,
  provideHttpClientTesting,
} from '@angular/common/http/testing';

import { retryInterceptor } from './retry.interceptor';

describe('retryInterceptor', () => {
  let http: HttpClient;
  let httpMock: HttpTestingController;
  beforeEach(() => {
    TestBed.configureTestingModule({
      providers: [
        provideHttpClient(withInterceptors([retryInterceptor])),
        provideHttpClientTesting(),
      ],
    });
    http = TestBed.inject(HttpClient);
    httpMock = TestBed.inject(HttpTestingController);
  });
  afterEach(() => {
    httpMock.verify();
  });

  it('should retry 3 times for retryable status', fakeAsync(() => {
    let actualError: HttpErrorResponse | undefined;
    http.post('/api/chat', {}).subscribe({
      error: (err) => (actualError = err),
    });
    httpMock.expectOne('/api/chat').flush(null, {
      status: 502,
      statusText: 'Bad Gateway',
    });
    tick(1000);
    httpMock.expectOne('/api/chat').flush(null, {
      status: 502,
      statusText: 'Bad Gateway',
    });
    tick(2000);
    httpMock.expectOne('/api/chat').flush(null, {
      status: 502,
      statusText: 'Bad Gateway',
    });
    tick(4000);
    httpMock.expectOne('/api/chat').flush(null, {
      status: 502,
      statusText: 'Bad Gateway',
    });
    expect(actualError?.status).toBe(502);
  }));

  it('should not retry requests outside /api/chat', () => {
    let actualError: HttpErrorResponse | undefined;
    http.get('/users').subscribe({
      error: (err) => (actualError = err),
    });
    httpMock.expectOne('/users').flush(null, {
      status: 502,
      statusText: 'Bad Gateway',
    });
    expect(actualError?.status).toBe(502);
  });

  it('should succeed after retry', fakeAsync(() => {
    let response: unknown;
    http.post('/api/chat', {}).subscribe({
      next: (res) => (response = res),
    });
    httpMock.expectOne('/api/chat').flush(null, {
      status: 503,
      statusText: 'Service Unavailable',
    });
    tick(1000);
    httpMock.expectOne('/api/chat').flush({
      success: true,
    });
    expect(response).toEqual({
      success: true,
    });
  }));
});
