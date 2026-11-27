import { inject, Injectable } from '@angular/core';
import { Router } from '@angular/router';
import {
  AuthUser,
  confirmSignUp,
  fetchAuthSession,
  getCurrentUser,
  signIn,
  signOut,
  signUp,
} from 'aws-amplify/auth';
import {
  BehaviorSubject,
  catchError,
  from,
  map,
  Observable,
  of,
  tap,
} from 'rxjs';
import { ENV_CONFIG } from '../environment.token';

export function isUserUnauthenticatedError(error: unknown): boolean {
  return (
    typeof error === 'object' &&
    error !== null &&
    (error as { name?: unknown }).name === 'UserUnAuthenticatedException'
  );
}

@Injectable({ providedIn: 'root' })
export class AuthService {
  private readonly environment = inject(ENV_CONFIG);
  private isAuthenticated$$ = new BehaviorSubject<boolean>(false);
  isAuthenticated$ = this.isAuthenticated$$.asObservable();

  private currentUser$$ = new BehaviorSubject<AuthUser | null>(null);
  currentUser$ = this.currentUser$$.asObservable();

  private router = inject(Router);

  constructor() {
    if (!this.environment.anonymousAccess) {
      this.checkAuthStatus();
    } else {
      this.isAuthenticated$$.next(true);
    }
  }

  async checkAuthStatus(): Promise<boolean> {
    if (this.environment.anonymousAccess) {
      this.isAuthenticated$$.next(true);
      return true;
    }
    try {
      const user = await getCurrentUser();
      const session = await fetchAuthSession();

      const isAuthenticated = !!session?.tokens?.idToken;
      this.isAuthenticated$$.next(isAuthenticated);

      if (isAuthenticated) {
        this.currentUser$$.next(user);
      }

      return isAuthenticated;
    } catch (error) {
      if (!isUserUnauthenticatedError(error)) {
        console.error('Authentication check failed', error);
      }
      this.isAuthenticated$$.next(false);
      this.currentUser$$.next(null);
      return false;
    }
  }

  login(username: string, password: string): Observable<boolean> {
    return from(signIn({ username, password })).pipe(
      tap(() => {
        this.isAuthenticated$$.next(true);
        this.router.navigate(['/chat']);
        this.checkAuthStatus();
      }),
      map(() => true),
      catchError((error) => {
        console.error('Login error', error);
        this.isAuthenticated$$.next(false);
        return of(false);
      }),
    );
  }

  async logout(): Promise<void> {
    try {
      await signOut();
      this.isAuthenticated$$.next(false);
      this.currentUser$$.next(null);
      this.router.navigate(['/login']);
    } catch (error) {
      console.error('Logout error', error);
    }
  }

  async getUser(): Promise<AuthUser | null> {
    try {
      const user = await getCurrentUser();
      this.currentUser$$.next(user);
      return user;
    } catch (error) {
      console.error('getUser error', error);
      this.currentUser$$.next(null);
      return null;
    }
  }

  register(
    username: string,
    password: string,
    email: string,
  ): Observable<{ success: boolean; requiresConfirmation: boolean }> {
    return from(
      signUp({
        username,
        password,
        options: {
          userAttributes: {
            email,
          },
        },
      }),
    ).pipe(
      map((result) => ({
        success: true,
        requiresConfirmation: !result.isSignUpComplete,
      })),
      catchError((error) => {
        console.error('Registration error', error);
        return of({ success: false, requiresConfirmation: false });
      }),
    );
  }

  confirmRegistration(username: string, code: string): Observable<boolean> {
    return from(confirmSignUp({ username, confirmationCode: code })).pipe(
      map(() => true),
      catchError((error) => {
        console.error('Confirmation error', error);
        return of(false);
      }),
    );
  }
}
