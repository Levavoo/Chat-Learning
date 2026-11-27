import { TestBed } from '@angular/core/testing';
import { MatomoService } from './matomo.service';

describe('MatomoService', () => {
  let service: MatomoService;

  const ALLOWED_HOSTNAME = 'rentenchat.deutsche-rentenversicherung.de';
  const QA_HOSTNAME = 'db7q31zqeevsz.cloudfront.net';
  const DISALLOWED_HOSTNAME = 'd11u7o0s8x8o66.cloudfront.net';

  function mockHostname(hostname: string): void {
    spyOn(service, '_getHostname').and.returnValue(hostname);
  }

  beforeEach(() => {
    TestBed.configureTestingModule({});
    service = TestBed.inject(MatomoService);
    window._paq = [];
    document
      .querySelectorAll('script[src*="matomo"]')
      .forEach((el) => el.remove());
  });

  afterEach(() => {
    service.destroy();
  });

  it('initialize() on prod hostname creates script element and configures _paq', () => {
    mockHostname(ALLOWED_HOSTNAME);
    service.initialize();

    const script = document.querySelector(
      'script[src*="matomo.js"]',
    ) as HTMLScriptElement;
    expect(script).toBeTruthy();
    expect(script.src).toContain('matomo.js');
    expect(script.async).toBeTrue();

    const commands = window._paq.map((cmd) => cmd[0]);
    expect(commands).toContain('setTrackerUrl');
    expect(commands).toContain('setSiteId');
    expect(commands).toContain('setExcludedQueryParams');
    expect(commands).toContain('enableLinkTracking');
  });

  it('initialize() pushes disableCookies before setTrackerUrl (#709)', () => {
    mockHostname(ALLOWED_HOSTNAME);
    service.initialize();

    const commands = window._paq.map((cmd) => cmd[0] as string);
    const disableIdx = commands.indexOf('disableCookies');
    const trackerIdx = commands.indexOf('setTrackerUrl');
    expect(disableIdx).toBeGreaterThanOrEqual(0);
    expect(disableIdx).toBeLessThan(trackerIdx);
  });

  it('initialize() on QA hostname also enables tracking', () => {
    mockHostname(QA_HOSTNAME);
    service.initialize();

    expect(service.isEnabled).toBeTrue();
    const script = document.querySelector('script[src*="matomo.js"]');
    expect(script).toBeTruthy();
  });

  it('initialize() is idempotent — second call creates only one script element', () => {
    mockHostname(ALLOWED_HOSTNAME);
    service.initialize();
    service.initialize();

    const scripts = document.querySelectorAll('script[src*="matomo.js"]');
    expect(scripts.length).toBe(1);
  });

  it('isEnabled returns true on allowed hostname', () => {
    mockHostname(ALLOWED_HOSTNAME);
    service.initialize();
    expect(service.isEnabled).toBeTrue();
  });

  it('initialize() on disallowed hostname does NOT create script element', () => {
    mockHostname(DISALLOWED_HOSTNAME);
    service.initialize();

    const script = document.querySelector('script[src*="matomo.js"]');
    expect(script).toBeNull();
  });

  it('initialize() on disallowed hostname leaves _paq empty', () => {
    mockHostname(DISALLOWED_HOSTNAME);
    window._paq = [];
    service.initialize();

    expect(window._paq.length).toBe(0);
  });

  it('isEnabled returns false on disallowed hostname', () => {
    mockHostname(DISALLOWED_HOSTNAME);
    service.initialize();
    expect(service.isEnabled).toBeFalse();
  });

  it('trackPageView() pushes setCustomUrl, setDocumentTitle, trackPageView when enabled', () => {
    mockHostname(ALLOWED_HOSTNAME);
    service.initialize();
    const countBefore = window._paq.length;

    service.trackPageView();

    const newCommands = window._paq
      .slice(countBefore)
      .map((cmd) => cmd[0] as string);
    expect(newCommands).toContain('setCustomUrl');
    expect(newCommands).toContain('setDocumentTitle');
    expect(newCommands).toContain('trackPageView');
  });

  it('trackPageView() is a no-op when disabled', () => {
    mockHostname(DISALLOWED_HOSTNAME);
    service.initialize();
    window._paq = [];

    service.trackPageView();

    expect(window._paq.length).toBe(0);
  });

  it('trackEvent() pushes trackEvent command with correct args when enabled', () => {
    mockHostname(ALLOWED_HOSTNAME);
    service.initialize();
    window._paq = [];

    service.trackEvent('Chatbot', 'Quelle-angezeigt', 'B01', 1);

    expect(window._paq.length).toBe(1);
    expect(window._paq[0]).toEqual([
      'trackEvent',
      'Chatbot',
      'Quelle-angezeigt',
      'B01',
      1,
    ]);
  });

  it('trackEvent() scopes Chatbot events to Chatbot-Test on QA', () => {
    mockHostname(QA_HOSTNAME);
    service.initialize();
    window._paq = [];

    service.trackEvent('Chatbot', 'Button', 'Hilfe');

    expect(window._paq[0]).toEqual([
      'trackEvent',
      'Chatbot-Test',
      'Button',
      'Hilfe',
      undefined,
    ]);
  });

  it('trackEvent() preserves non-Chatbot categories on QA', () => {
    mockHostname(QA_HOSTNAME);
    service.initialize();
    window._paq = [];

    service.trackEvent('Other', 'Action', 'Name');

    expect(window._paq[0]).toEqual([
      'trackEvent',
      'Other',
      'Action',
      'Name',
      undefined,
    ]);
  });

  it('trackEvent() is a no-op when disabled', () => {
    mockHostname(DISALLOWED_HOSTNAME);
    service.initialize();
    window._paq = [];

    service.trackEvent('Chatbot', 'Button', 'Hilfe');

    expect(window._paq.length).toBe(0);
  });

  it('hashchange event triggers trackPageView', (done) => {
    mockHostname(ALLOWED_HOSTNAME);
    service.initialize();
    const spy = spyOn(service, 'trackPageView').and.callThrough();

    window.dispatchEvent(new Event('hashchange'));

    setTimeout(() => {
      expect(spy).toHaveBeenCalled();
      done();
    }, 50);
  });

  it('destroy() removes script element and disables tracking', () => {
    mockHostname(ALLOWED_HOSTNAME);
    service.initialize();
    expect(service.isEnabled).toBeTrue();

    service.destroy();

    expect(service.isEnabled).toBeFalse();
    const script = document.querySelector('script[src*="matomo.js"]');
    expect(script).toBeNull();
  });

  it('destroy() restores original history methods so they no longer track', () => {
    mockHostname(ALLOWED_HOSTNAME);
    service.initialize();
    expect(service.isEnabled).toBeTrue();

    service.destroy();

    window._paq = [];
    window.history.pushState({}, '', '/test');
    expect(window._paq.length).toBe(0);
  });
});
