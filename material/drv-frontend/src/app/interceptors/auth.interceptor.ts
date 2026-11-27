import {
  HttpRequest,
  HttpHandlerFn,
  HttpEvent,
  HttpErrorResponse,
  HttpInterceptorFn,
} from '@angular/common/http';
import { Observable, from, throwError } from 'rxjs';
import { catchError, switchMap } from 'rxjs/operators';
import { fetchAuthSession } from 'aws-amplify/auth';
import { inject, InjectionToken } from '@angular/core';
import { ENV_CONFIG } from '../environment.token';

export const FETCH_AUTH_SESSION = new InjectionToken('FETCH_AUTH_SESSION', {
  providedIn: 'root',
  factory: () => fetchAuthSession,
});

const shouldSkipAuth = (url: string): boolean => {
  const environment = inject(ENV_CONFIG);
  if (environment.anonymousAccess) {
    return true;
  }
  const skipAuthUrls = ['/health'];
  return skipAuthUrls.some((skipUrl) => url.includes(skipUrl));
};

const getAuthToken = async (): Promise<string | null> => {
  try {
    const fetchAuthSessionFn = inject(FETCH_AUTH_SESSION);
    const session = await fetchAuthSessionFn();

    return session.tokens?.idToken?.toString() || null;
  } catch (error) {
    console.error('Error getting auth token:', error);
    return null;
  }
};

export const authInterceptor: HttpInterceptorFn = (
  request: HttpRequest<unknown>,
  next: HttpHandlerFn,
): Observable<HttpEvent<unknown>> => {
  if (shouldSkipAuth(request.url)) {
    return next(request);
  }

  return from(getAuthToken()).pipe(
    switchMap((token) => {
      if (token) {
        request = request.clone({
          setHeaders: {
            Authorization: `Bearer ${token}`,
          },
        });
      }

      return next(request);
    }),
    catchError((error: HttpErrorResponse) => {
      if (error.status === 401 || error.status === 403) {
        console.error('Authentication error:', error);
      }
      return throwError(() => error);
    }),
  );
};
