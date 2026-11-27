import { inject, Injectable } from '@angular/core';
import {
  BehaviorSubject,
  combineLatest,
  filter,
  Observable,
  switchMap,
  take,
} from 'rxjs';
import { ApiProxyService } from './api-proxy/api-proxy.service';
import { HttpClient, HttpHeaders } from '@angular/common/http';

@Injectable({
  providedIn: 'root',
})
export class DisclaimerService {
  isDisclaimerAccepted$: BehaviorSubject<boolean> =
    new BehaviorSubject<boolean>(false);
  isConsentAccepted$: BehaviorSubject<boolean> = new BehaviorSubject<boolean>(
    false,
  );

  private readonly apiProxyService = inject(ApiProxyService);
  private readonly http = inject(HttpClient);

  public saveConsent(sessionId: string): Observable<{ status: string }> {
    const consentUrl = `${this.apiProxyService.consentUrl}`;

    return this.http.post<{ status: string }>(
      consentUrl,
      { sessionId },
      {
        headers: new HttpHeaders({
          'Content-Type': 'application/json',
        }),
      },
    );
  }

  public initConsentSaving(sessionId: string): void {
    combineLatest([this.getDisclaimerAccepted$(), this.getConsentAccepted$()])
      .pipe(
        filter(
          ([disclaimerAccepted, consentAccepted]) =>
            disclaimerAccepted && consentAccepted,
        ),
        take(1),
        switchMap(() => this.saveConsent(sessionId)),
      )
      .subscribe({
        error: (error) => {
          console.error('Error saving consent', error);
        },
      });
  }

  acceptDisclaimer(): void {
    this.isDisclaimerAccepted$.next(true);
  }

  toggleDisclaimer(): void {
    this.isDisclaimerAccepted$.next(!this.isDisclaimerAccepted$.value);
  }

  acceptConsent(): void {
    this.isConsentAccepted$.next(true);
  }

  toggleConsent(): void {
    this.isConsentAccepted$.next(!this.isConsentAccepted$.value);
  }

  getDisclaimerAccepted$(): Observable<boolean> {
    return this.isDisclaimerAccepted$.asObservable();
  }

  getConsentAccepted$(): Observable<boolean> {
    return this.isConsentAccepted$.asObservable();
  }
}
