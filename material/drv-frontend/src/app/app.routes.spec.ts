import {} from 'jasmine';
import { buildRoutes } from './app.routes';
import { LoginComponent } from 'src/app/pages/login/login.component';
import { RegisterComponent } from 'src/app/pages/register/register.component';

describe('buildRoutes', () => {
  const findPath = (routes: ReturnType<typeof buildRoutes>, path: string) =>
    routes.find((r) => r.path === path);

  describe('when skipAuth is true (anonymous access)', () => {
    it('does not register /login or /register (external)', () => {
      const routes = buildRoutes({ intern: false, skipAuth: true });

      expect(findPath(routes, 'login')).toBeUndefined();
      expect(findPath(routes, 'register')).toBeUndefined();
    });

    it('does not register /login or /register (intern)', () => {
      const routes = buildRoutes({ intern: true, skipAuth: true });

      expect(findPath(routes, 'login')).toBeUndefined();
      expect(findPath(routes, 'register')).toBeUndefined();
    });

    it('redirects root to /chat', () => {
      const routes = buildRoutes({ intern: false, skipAuth: true });

      expect(findPath(routes, '')?.redirectTo).toBe('/chat');
    });

    it('routes unknown paths to chat (wildcard)', () => {
      const routes = buildRoutes({ intern: false, skipAuth: true });

      expect(findPath(routes, '**')?.redirectTo).toBe('chat');
    });
  });

  describe('when skipAuth is false', () => {
    it('registers /login and /register with their components', () => {
      const routes = buildRoutes({ intern: false, skipAuth: false });

      expect(findPath(routes, 'login')?.component).toBe(LoginComponent);
      expect(findPath(routes, 'register')?.component).toBe(RegisterComponent);
    });

    it('redirects root to /login', () => {
      const routes = buildRoutes({ intern: false, skipAuth: false });

      expect(findPath(routes, '')?.redirectTo).toBe('/login');
    });
  });
});
