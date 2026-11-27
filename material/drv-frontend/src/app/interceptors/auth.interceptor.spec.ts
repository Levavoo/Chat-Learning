import { TestBed } from '@angular/core/testing';
import {
  HttpRequest,
  HttpHandlerFn,
  HttpEvent,
  HttpResponse,
} from '@angular/common/http';
import {} from 'jasmine';
import { Observable, of } from 'rxjs';
import { ENV_CONFIG } from '../environment.token';
import { EnvironmentConfig } from 'src/environments/environment-config';
import { authInterceptor, FETCH_AUTH_SESSION } from './auth.interceptor';

describe('authInterceptor', () => {
  let envConfig: EnvironmentConfig;

  beforeEach(() => {
    envConfig = {
      apiEndpoint: '',
      userPoolId: '',
      userPoolClientId: '',
      region: '',
      redirectSigninUrl: '',
      redirectSignoutUrl: '',
      cognitoDomain: '',
      anonymousAccess: false,
      intern: false,
    };

    TestBed.configureTestingModule({
      providers: [
        {
          provide: ENV_CONFIG,
          useValue: envConfig,
        },
        {
          provide: FETCH_AUTH_SESSION,
          useValue: jasmine.createSpy().and.returnValue(
            Promise.resolve({
              tokens: {
                idToken: {
                  toString: () => 'mock-token',
                },
              },
            }),
          ),
        },
      ],
    });
  });

  const captureForwardedRequest = (
    request: HttpRequest<unknown>,
    onForwarded: (forwarded: HttpRequest<unknown>) => void,
    done: DoneFn,
  ): void => {
    let forwarded: HttpRequest<unknown> | undefined;

    const next: HttpHandlerFn = (
      req: HttpRequest<unknown>,
    ): Observable<HttpEvent<unknown>> => {
      forwarded = req;
      return of(new HttpResponse({ status: 200 }));
    };

    TestBed.runInInjectionContext(() => {
      authInterceptor(request, next).subscribe(() => {
        expect(forwarded).toBeDefined();
        onForwarded(forwarded as HttpRequest<unknown>);
        done();
      });
    });
  };

  it('sets Authorization header when skipAuth is false', (done) => {
    envConfig.anonymousAccess = false;

    captureForwardedRequest(
      new HttpRequest('GET', '/api/data'),
      (forwarded) => {
        expect(forwarded.headers.get('Authorization')).toBe(
          'Bearer mock-token',
        );
      },
      done,
    );
  });

  it('does not set an Authorization header when skipAuth is true', (done) => {
    envConfig.anonymousAccess = true;

    captureForwardedRequest(
      new HttpRequest('GET', '/api/data'),
      (forwarded) => {
        expect(forwarded.headers.has('Authorization')).toBeFalse();
      },
      done,
    );
  });

  it('does not set an Authorization header for skip-listed URLs', (done) => {
    envConfig.anonymousAccess = false;

    captureForwardedRequest(
      new HttpRequest('GET', '/health'),
      (forwarded) => {
        expect(forwarded.headers.has('Authorization')).toBeFalse();
      },
      done,
    );
  });
});
