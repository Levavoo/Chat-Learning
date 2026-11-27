import { inject, Injectable } from '@angular/core';
import { Amplify } from 'aws-amplify';
import { BehaviorSubject, Observable } from 'rxjs';
import { ENV_CONFIG } from 'src/app/environment.token';

export interface ApiConfig {
  apiUrl: string;
  chatEndpoints?: {
    conversation: string;
    getConversation: string;
    getConversations: string;
    health: string;
    consent: string;
    deleteSession: string;
  };
}
export interface AmplifyConfig {
  Auth: {
    Cognito: {
      userPoolId: string;
      userPoolClientId: string;
    };
  };
  API?: {
    REST: {
      apiGateway: {
        endpoint: string;
        region?: string;
      };
    };
  };
}

// Resolves API URLs and keys at runtime instead of hard-coding them per build.
@Injectable({
  providedIn: 'root',
})
export class ApiProxyService {
  private configLoaded = new BehaviorSubject<boolean>(false);
  private config: ApiConfig | null = null;
  private readonly env = inject(ENV_CONFIG);
  private chatEndpoints: {
    conversation: string;
    getConversation: string;
    getConversations: string;
    health: string;
    consent: string;
    deleteSession: string;
  } = {
    conversation: '/api/chat',
    getConversation: '/api/chat',
    getConversations: '/api/conversations',
    health: '/health',
    consent: '/api/consent',
    deleteSession: '/api/session',
  };

  constructor() {
    this.configureAmplify();
    this.initialize();
  }

  async initialize(): Promise<void> {
    try {
      const apiEndpoint = this.env.apiEndpoint;
      if (apiEndpoint != null) {
        // Empty string => same-origin (API routed through CloudFront).
        this.config = {
          apiUrl: apiEndpoint,
          chatEndpoints: this.chatEndpoints,
        };
        this.configLoaded.next(true);
      } else {
        throw new Error('API endpoint configuration not found');
      }
    } catch (error) {
      if (this.isLocalhost()) {
        this.config = {
          apiUrl: 'http://localhost:8000',
          chatEndpoints: this.chatEndpoints,
        };
        this.configLoaded.next(true);
        console.warn('Using fallback development configuration', error);
      }
    }
  }

  get isConfigLoaded(): Observable<boolean> {
    return this.configLoaded.asObservable();
  }

  get apiUrl(): string {
    if (!this.config?.apiUrl) {
      console.error(
        'API URL not available. Make sure initialize() was called.',
      );
      return '';
    }
    return this.config.apiUrl;
  }

  private configureAmplify(): void {
    const userPoolId = this.env.userPoolId;
    const userPoolClientId = this.env.userPoolClientId;
    const region = this.env.region;

    if (userPoolId && userPoolClientId) {
      try {
        const amplifyConfig: AmplifyConfig = {
          Auth: {
            Cognito: {
              userPoolId: userPoolId,
              userPoolClientId: userPoolClientId,
            },
          },
        };

        // Skip REST API config on empty endpoint (same-origin via CloudFront).
        const apiEndpoint = this.env.apiEndpoint;
        if (apiEndpoint) {
          amplifyConfig.API = {
            REST: {
              apiGateway: {
                endpoint: apiEndpoint,
                region: region,
              },
            },
          };
        }

        Amplify.configure(amplifyConfig);
      } catch (error) {
        console.error('Error configuring AWS Amplify:', error);
      }
    } else {
      console.warn(
        'Missing Cognito configuration. Authentication will not work.',
      );
    }
  }

  get getChatEndpoints(): {
    conversation: string;
    getConversation: string;
    getConversations: string;
    health: string;
    consent: string;
    deleteSession: string;
  } {
    const defaultEndpoints = {
      conversation: '/api/chat',
      getConversation: '/api/chat',
      getConversations: '/api/conversations',
      health: '/health',
      consent: '/api/consent',
      deleteSession: '/api/session',
    };

    return this.config?.chatEndpoints || this.chatEndpoints || defaultEndpoints;
  }

  get conversationUrl(): string {
    return `${this.apiUrl.replace(/\/+$/, '')}${this.getChatEndpoints.conversation}`;
  }

  get consentUrl(): string {
    return `${this.apiUrl.replace(/\/+$/, '')}${this.getChatEndpoints.consent}`;
  }

  get deleteSessionUrl(): string {
    return `${this.apiUrl.replace(/\/+$/, '')}${this.getChatEndpoints.deleteSession}`;
  }

  get conversationsUrl(): string {
    return `${this.apiUrl.replace(/\/+$/, '')}${this.getChatEndpoints.getConversations}`;
  }

  get healthUrl(): string {
    return `${this.apiUrl.replace(/\/+$/, '')}${this.getChatEndpoints.health}`;
  }

  private isLocalhost(): boolean {
    return location.hostname === 'localhost';
  }
}
