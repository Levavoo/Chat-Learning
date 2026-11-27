import { APP_INITIALIZER } from '@angular/core';
import { ApiProxyService } from '@services/api-proxy/api-proxy.service';
import { MatomoService } from '@services/matomo/matomo.service';

export function initApiConfig(apiProxyService: ApiProxyService) {
  return () => {
    return apiProxyService.initialize();
  };
}

export const ApiConfigInitializerProvider = {
  provide: APP_INITIALIZER,
  useFactory: initApiConfig,
  deps: [ApiProxyService],
  multi: true,
};

export function initMatomo(matomo: MatomoService) {
  return () => matomo.initialize();
}

// No-op on hostnames outside the TRACKING_HOSTNAMES allowlist (MatomoService).
export const MatomoInitializerProvider = {
  provide: APP_INITIALIZER,
  useFactory: initMatomo,
  deps: [MatomoService],
  multi: true,
};
