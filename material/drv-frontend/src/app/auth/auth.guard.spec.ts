import { TestBed } from '@angular/core/testing';
import { Router } from '@angular/router';
import {} from 'jasmine';
import { of } from 'rxjs';
import { AuthGuard } from './auth.guard';
import { AuthService } from './auth.service';
import { ENV_CONFIG } from '../environment.token';
import { EnvironmentConfig } from 'src/environments/environment-config';

describe('AuthGuard', () => {
  let guard: AuthGuard;
  let envConfig: EnvironmentConfig;

  const authServiceMock = {
    isAuthenticated$: of(false),
  };

  const routerMock = {
    parseUrl: jasmine.createSpy('parseUrl'),
  };

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

    routerMock.parseUrl.calls.reset();

    TestBed.configureTestingModule({
      providers: [
        AuthGuard,
        { provide: ENV_CONFIG, useValue: envConfig },
        { provide: AuthService, useValue: authServiceMock },
        { provide: Router, useValue: routerMock },
      ],
    });

    guard = TestBed.inject(AuthGuard);
  });

  it('allows the route without a token when skipAuth is true', () => {
    envConfig.anonymousAccess = true;

    expect(guard.canActivate()).toBeTrue();
    expect(routerMock.parseUrl).not.toHaveBeenCalled();
  });
});
