import { inject, Injectable } from '@angular/core';
import { Router } from '@angular/router';
import { fetchAuthSession } from 'aws-amplify/auth';
import { ENV_CONFIG } from '../environment.token';

const DASHBOARD_GROUP = 'dashboard-admins';

@Injectable({ providedIn: 'root' })
export class DashboardGuard {
  private readonly router = inject(Router);
  private readonly environment = inject(ENV_CONFIG);

  async canActivate(): Promise<boolean> {
    if (this.environment.anonymousAccess) {
      return true;
    }
    try {
      const session = await fetchAuthSession();
      const groups =
        (session.tokens?.idToken?.payload['cognito:groups'] as string[]) ?? [];
      if (groups.includes(DASHBOARD_GROUP)) {
        return true;
      }
    } catch {
      /* not authenticated */
    }
    this.router.navigate(['/']);
    return false;
  }
}
