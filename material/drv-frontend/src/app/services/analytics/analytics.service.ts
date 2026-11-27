import { HttpClient } from '@angular/common/http';
import { inject, Injectable } from '@angular/core';
import { ApiProxyService } from '@services/api-proxy/api-proxy.service';
import { components } from '../../types/api.generated';
import { Observable } from 'rxjs';

export type AnalyticsResponse = components['schemas']['AnalyticsResponse'];
export type DocumentInventoryResponse =
  components['schemas']['DocumentInventoryResponse'];
export type DocumentInventoryItem =
  components['schemas']['DocumentInventoryItem'];

@Injectable({ providedIn: 'root' })
export class AnalyticsService {
  private readonly http = inject(HttpClient);
  private readonly apiProxy = inject(ApiProxyService);

  getAnalytics(fromTs?: number, toTs?: number): Observable<AnalyticsResponse> {
    const base = this.apiProxy.apiUrl.replace(/\/+$/, '');
    const params = new URLSearchParams();
    if (fromTs != null) params.set('from_ts', String(fromTs));
    if (toTs != null) params.set('to_ts', String(toTs));
    const qs = params.toString();
    const url = qs ? `${base}/api/analytics?${qs}` : `${base}/api/analytics`;
    return this.http.get<AnalyticsResponse>(url);
  }

  getDocuments(): Observable<DocumentInventoryResponse> {
    const base = this.apiProxy.apiUrl.replace(/\/+$/, '');
    return this.http.get<DocumentInventoryResponse>(
      `${base}/api/analytics/documents`,
    );
  }
}
