import { TestBed } from '@angular/core/testing';

import { DisclaimerService } from './disclaimer.service';
import { ApiProxyService } from './api-proxy/api-proxy.service';
import { provideHttpClient } from '@angular/common/http';
import {
  HttpTestingController,
  provideHttpClientTesting,
} from '@angular/common/http/testing';

describe('DisclaimerService', () => {
  let service: DisclaimerService;
  let httpMock: HttpTestingController;

  const apiProxyServiceMock = {
    consentUrl: 'http://mock-api.consent',
  };
  beforeEach(() => {
    TestBed.configureTestingModule({
      providers: [
        {
          provide: ApiProxyService,
          useValue: apiProxyServiceMock,
        },
        provideHttpClient(),
        provideHttpClientTesting(),
      ],
    });
    service = TestBed.inject(DisclaimerService);
    httpMock = TestBed.inject(HttpTestingController);
  });

  afterEach(() => {
    httpMock.verify();
  });

  it('should be created', () => {
    expect(service).toBeTruthy();
  });

  describe('disclaimer state', () => {
    it('should accept disclaimer', (done) => {
      service.acceptDisclaimer();
      service.getDisclaimerAccepted$().subscribe((value) => {
        expect(value).toBeTrue();
        done();
      });
    });
    it('should toggle disclaimer', () => {
      expect(service.isDisclaimerAccepted$.value).toBeFalse();
      service.toggleDisclaimer();
      expect(service.isDisclaimerAccepted$.value).toBeTrue();
      service.toggleDisclaimer();
      expect(service.isDisclaimerAccepted$.value).toBeFalse();
    });
  });

  describe('consent state', () => {
    it('should accept consent', (done) => {
      service.acceptConsent();
      service.getConsentAccepted$().subscribe((value) => {
        expect(value).toBeTrue();
        done();
      });
    });
    it('should toggle consent', () => {
      expect(service.isConsentAccepted$.value).toBeFalse();
      service.toggleConsent();
      expect(service.isConsentAccepted$.value).toBeTrue();
      service.toggleConsent();
      expect(service.isConsentAccepted$.value).toBeFalse();
    });
  });

  describe('saveConsent', () => {
    it('should send POST request with sessionId', () => {
      const sessionId = 'session-123';
      const mockResponse = { status: 'success' };
      service.saveConsent(sessionId).subscribe((response) => {
        expect(response).toEqual(mockResponse);
      });
      const req = httpMock.expectOne(apiProxyServiceMock.consentUrl);
      expect(req.request.method).toBe('POST');
      expect(req.request.body).toEqual({ sessionId });
      req.flush(mockResponse);
    });
  });

  describe('initConsentSaving', () => {
    it('should save consent when both disclaimer and consent are accepted', () => {
      spyOn(service, 'saveConsent').and.callThrough();
      service.initConsentSaving('session-123');
      service.acceptDisclaimer();
      service.acceptConsent();
      const req = httpMock.expectOne(apiProxyServiceMock.consentUrl);
      expect(service.saveConsent).toHaveBeenCalledWith('session-123');
      req.flush({ status: 'success' });
    });
    it('should not save consent when only disclaimer is accepted', () => {
      spyOn(service, 'saveConsent').and.callThrough();
      service.initConsentSaving('session-123');
      service.acceptDisclaimer();
      httpMock.expectNone(apiProxyServiceMock.consentUrl);
      expect(service.saveConsent).not.toHaveBeenCalled();
    });
    it('should not save consent when only consent is accepted', () => {
      spyOn(service, 'saveConsent').and.callThrough();
      service.initConsentSaving('session-123');
      service.acceptConsent();
      httpMock.expectNone(apiProxyServiceMock.consentUrl);
      expect(service.saveConsent).not.toHaveBeenCalled();
    });
    it('should only save consent once due to take(1)', () => {
      spyOn(service, 'saveConsent').and.callThrough();
      service.initConsentSaving('session-123');
      service.acceptDisclaimer();
      service.acceptConsent();
      const req = httpMock.expectOne(apiProxyServiceMock.consentUrl);
      req.flush({ status: 'success' });
      service.toggleDisclaimer();
      service.toggleDisclaimer();
      httpMock.expectNone(apiProxyServiceMock.consentUrl);
      expect(service.saveConsent).toHaveBeenCalledTimes(1);
    });
  });
});
