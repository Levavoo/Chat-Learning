import { Injectable } from '@angular/core';

// TODO(#682): remove QA hostname after go-live on prod.
const PROD_HOSTNAME = 'rentenchat.deutsche-rentenversicherung.de';
const QA_HOSTNAME = 'db7q31zqeevsz.cloudfront.net';
const TRACKING_HOSTNAMES = [PROD_HOSTNAME, QA_HOSTNAME];

// QA shares the Matomo site ID with prod; scope its events to a separate category until it gets its own site.
const CHATBOT_EVENT_CATEGORY = 'Chatbot';
const QA_CHATBOT_EVENT_CATEGORY = 'Chatbot-Test';

const MATOMO_URL = '//www.deutsche-rentenversicherung.de/matomo/';
const SITE_ID = '191';

declare global {
  interface Window {
    _paq: unknown[][];
  }
}

// Active only on hostnames in TRACKING_HOSTNAMES; public methods are no-ops otherwise.
@Injectable({ providedIn: 'root' })
export class MatomoService {
  private enabled = false;
  private initialized = false;
  private scriptElement: HTMLScriptElement | null = null;

  /** @internal override in tests to mock the environment. */
  _getHostname(): string {
    return window.location.hostname;
  }

  // Originals captured for destroy() test isolation.
  private originalPushState = window.history.pushState.bind(window.history);
  private originalReplaceState = window.history.replaceState.bind(
    window.history,
  );

  private readonly boundHashChange = () =>
    setTimeout(() => this.trackPageView(), 0);
  private readonly boundPopState = () =>
    setTimeout(() => this.trackPageView(), 0);

  // Idempotent; no-op on hostnames outside TRACKING_HOSTNAMES.
  initialize(): void {
    if (this.initialized) {
      return;
    }
    this.initialized = true;

    const hostname = this._getHostname();
    if (!TRACKING_HOSTNAMES.includes(hostname)) {
      this.enabled = false;
      return;
    }

    this.enabled = true;

    window._paq = window._paq || [];
    window._paq.push(['disableCookies']);
    window._paq.push([
      'setExcludedQueryParams',
      ['v', 'https', 'jsessionid', 'nn', 'ved', 'resourceid'],
    ]);
    window._paq.push(['setTrackerUrl', MATOMO_URL + 'matomo.php']);
    window._paq.push(['setSiteId', SITE_ID]);
    window._paq.push(['enableLinkTracking']);

    // Dynamically load matomo.js
    const script = document.createElement('script');
    script.async = true;
    script.src = MATOMO_URL + 'matomo.js';
    document.head.appendChild(script);
    this.scriptElement = script;

    this.trackPageView();
    this.wireSpaListeners();
  }

  trackPageView(): void {
    if (!this.enabled) {
      return;
    }
    window._paq.push([
      'setCustomUrl',
      window.location.pathname + window.location.search + window.location.hash,
    ]);
    window._paq.push(['setDocumentTitle', document.title]);
    window._paq.push(['trackPageView']);
  }

  trackEvent(
    category: string,
    action: string,
    name?: string,
    value?: number,
  ): void {
    if (!this.enabled) {
      return;
    }
    const eventCategory =
      this._getHostname() === QA_HOSTNAME && category === CHATBOT_EVENT_CATEGORY
        ? QA_CHATBOT_EVENT_CATEGORY
        : category;
    window._paq.push(['trackEvent', eventCategory, action, name, value]);
  }

  get isEnabled(): boolean {
    return this.enabled;
  }

  // FOR TEST ISOLATION ONLY — root singletons are never torn down at runtime.
  destroy(): void {
    window.history.pushState = this.originalPushState;
    window.history.replaceState = this.originalReplaceState;
    window.removeEventListener('hashchange', this.boundHashChange);
    window.removeEventListener('popstate', this.boundPopState);

    if (this.scriptElement && this.scriptElement.parentNode) {
      this.scriptElement.parentNode.removeChild(this.scriptElement);
      this.scriptElement = null;
    }

    this.enabled = false;
    this.initialized = false;
  }

  // hashchange is the primary SPA trigger (withHashLocation()); push/replace patches are defensive.
  private wireSpaListeners(): void {
    const originalPush = this.originalPushState;
    const originalReplace = this.originalReplaceState;
    const trackPage = () => setTimeout(() => this.trackPageView(), 0);

    window.history.pushState = function (...args) {
      const result = originalPush.apply(window.history, args);
      trackPage();
      return result;
    };

    window.history.replaceState = function (...args) {
      const result = originalReplace.apply(window.history, args);
      trackPage();
      return result;
    };

    window.addEventListener('hashchange', this.boundHashChange);
    window.addEventListener('popstate', this.boundPopState);
  }
}
