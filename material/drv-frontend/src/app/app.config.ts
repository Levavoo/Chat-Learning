import {
  ApplicationConfig,
  ErrorHandler,
  provideZoneChangeDetection,
} from '@angular/core';
import { provideRouter, withHashLocation } from '@angular/router';
import { routes } from './app.routes';
import { provideHttpClient, withInterceptors } from '@angular/common/http';
import {
  ApiConfigInitializerProvider,
  MatomoInitializerProvider,
} from './app.initializer';
import { authInterceptor } from './interceptors/auth.interceptor';
import {
  CONFIG_TOKEN,
  DEFAULT_CONFIG_PUBLIC,
} from '@drv-ds/drv-design-system-ng';
import { GlobalErrorHandlerService } from '@services/global-error-handler.service';
import { errorInterceptor } from './interceptors/error.interceptor';
import { retryInterceptor } from './interceptors/retry.interceptor';
import { ENV_CONFIG } from './environment.token';

export const appConfig: ApplicationConfig = {
  providers: [
    {
      provide: ENV_CONFIG,
      useValue: {
        apiEndpoint: import.meta.env.NG_APP_API_ENDPOINT,
        userPoolId: import.meta.env.NG_APP_USER_POOL_ID,
        userPoolClientId: import.meta.env.NG_APP_USER_POOL_CLIENT_ID,
        region: import.meta.env.NG_APP_REGION,
        redirectSigninUrl: import.meta.env?.NG_APP_REDIRECT_SIGNIN_URL,
        redirectSignoutUrl: import.meta.env?.NG_APP_REDIRECT_SIGNOUT_URL,
        cognitoDomain: import.meta.env?.NG_APP_COGNITO_DOMAIN,
        anonymousAccess: import.meta.env.NG_APP_ANONYMOUS_ACCESS === 'true',
        intern: import.meta.env.NG_APP_INTERN === 'true',
      },
    },
    {
      provide: CONFIG_TOKEN,
      useValue: {
        ...DEFAULT_CONFIG_PUBLIC,
        spritePath: 'img/sprite.svg',
        pictogramSpritePath: 'img/pictograms.svg',
      },
    },
    provideZoneChangeDetection({ eventCoalescing: true }),
    { provide: ErrorHandler, useClass: GlobalErrorHandlerService },
    provideRouter(routes, withHashLocation()),
    provideHttpClient(
      withInterceptors([authInterceptor, errorInterceptor, retryInterceptor]),
    ),
    ApiConfigInitializerProvider,
    MatomoInitializerProvider,
  ],
};
