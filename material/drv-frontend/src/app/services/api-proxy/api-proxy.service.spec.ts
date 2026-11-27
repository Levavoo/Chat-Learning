import { TestBed } from '@angular/core/testing';
import { Amplify } from 'aws-amplify';

import { ApiProxyService } from './api-proxy.service';
import { EnvironmentConfig } from 'src/environments/environment-config';
import { ENV_CONFIG } from 'src/app/environment.token';

describe('ApiProxyService', () => {
  let service: ApiProxyService;

  const mockEnv: EnvironmentConfig = {
    apiEndpoint: 'https://api.example.com',
    userPoolId: 'pool-id',
    userPoolClientId: 'client-id',
    region: 'eu-central-1',
    redirectSigninUrl: '',
    redirectSignoutUrl: '',
    cognitoDomain: '',
    anonymousAccess: false,
    intern: false,
  };

  beforeEach(() => {
    spyOn(Amplify, 'configure');

    TestBed.configureTestingModule({
      providers: [
        {
          provide: ENV_CONFIG,
          useValue: mockEnv,
        },
      ],
    });

    service = TestBed.inject(ApiProxyService);
  });

  it('should be created', () => {
    expect(service).toBeTruthy();
  });

  it('should configure Amplify on creation', () => {
    expect(Amplify.configure).toHaveBeenCalled();
  });

  it('should initialize api configuration', async () => {
    await service.initialize();

    expect(service.apiUrl).toBe('https://api.example.com');
  });

  it('should expose correct conversation url', async () => {
    await service.initialize();

    expect(service.conversationUrl).toBe('https://api.example.com/api/chat');
  });

  it('should expose correct consent url', async () => {
    await service.initialize();

    expect(service.consentUrl).toBe('https://api.example.com/api/consent');
  });

  it('should expose correct delete session url', async () => {
    await service.initialize();

    expect(service.deleteSessionUrl).toBe(
      'https://api.example.com/api/session',
    );
  });

  it('should expose correct conversations url', async () => {
    await service.initialize();

    expect(service.conversationsUrl).toBe(
      'https://api.example.com/api/conversations',
    );
  });

  it('should expose correct health url', async () => {
    await service.initialize();

    expect(service.healthUrl).toBe('https://api.example.com/health');
  });

  it('should return chat endpoints', () => {
    const endpoints = service.getChatEndpoints;

    expect(endpoints.conversation).toBe('/api/chat');
    expect(endpoints.getConversations).toBe('/api/conversations');
    expect(endpoints.health).toBe('/health');
  });

  it('should emit config loaded', (done) => {
    service.isConfigLoaded.subscribe((loaded) => {
      if (loaded) {
        expect(loaded).toBeTrue();
        done();
      }
    });
  });
});
