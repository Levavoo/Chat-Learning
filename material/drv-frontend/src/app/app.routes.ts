import { Routes } from '@angular/router';
import { AuthGuard } from '@auth/auth.guard';
import { DisclaimerComponent } from '@components/disclaimer/disclaimer.component';
import { LoginComponent } from 'src/app/pages/login/login.component';
import { RegisterComponent } from 'src/app/pages/register/register.component';
import { ChatPageComponent } from './pages/chat-page/chat-page.component';
import { DashboardPageComponent } from './pages/dashboard/dashboard-page.component';
import { DashboardGuard } from './auth/dashboard.guard';
import { environment } from 'src/environments/environment';
import { ConsentComponent } from '@components/consent/consent.component';

export function buildRoutes(env: {
  intern: boolean;
  skipAuth: boolean;
}): Routes {
  const authRoutes: Routes = env.skipAuth
    ? []
    : [
        {
          path: 'login',
          component: LoginComponent,
        },
        {
          path: 'register',
          component: RegisterComponent,
        },
      ];

  const rootRedirect: Routes = [
    {
      path: '',
      redirectTo: env.skipAuth ? '/chat' : '/login',
      pathMatch: 'full',
    },
  ];

  const chatAndWildcard: Routes = [
    {
      path: 'chat',
      component: ChatPageComponent,
      data: { breadcrumb: 'Chat' },
      canActivate: [AuthGuard],
    },
    {
      path: 'r3d4kt10n',
      component: DashboardPageComponent,
      data: { breadcrumb: 'Dashboard' },
      canActivate: [DashboardGuard],
    },
    {
      path: '**',
      redirectTo: 'chat',
    },
  ];

  if (env.intern) {
    return [...rootRedirect, ...authRoutes, ...chatAndWildcard];
  }

  return [
    ...rootRedirect,
    ...authRoutes,
    {
      path: 'disclaimer',
      component: DisclaimerComponent,
    },
    {
      path: 'consent',
      component: ConsentComponent,
    },
    ...chatAndWildcard,
  ];
}

export const routes: Routes = buildRoutes(environment);
