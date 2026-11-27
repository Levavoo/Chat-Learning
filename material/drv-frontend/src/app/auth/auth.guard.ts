import { inject, Injectable } from '@angular/core';
import { CanActivate, Router } from '@angular/router';
import { map } from 'rxjs/operators';
import { AuthService } from './auth.service';
import { ENV_CONFIG } from '../environment.token';

@Injectable({ providedIn: 'root' })
export class AuthGuard implements CanActivate {
  private readonly authService: AuthService = inject(AuthService);
  private readonly router: Router = inject(Router);
  private readonly environment = inject(ENV_CONFIG);

  canActivate() {
    if (this.environment.anonymousAccess) {
      return true;
    }
    return this.authService.isAuthenticated$.pipe(
      map((isAuth) => isAuth || this.router.parseUrl('/login')),
    );
  }
}
