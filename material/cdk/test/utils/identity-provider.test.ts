import {
  identityProvider,
  TIdentityProvider,
} from '../../lib/utils/identity-provider';
import { aws_cognito } from 'aws-cdk-lib';

describe('identityProvider', () => {
  describe('isExist', () => {
    test('should return false when no providers are configured', () => {
      const idp = identityProvider([]);
      expect(idp.isExist()).toBe(false);
    });

    test('should return true when providers are configured', () => {
      const providers: TIdentityProvider[] = [
        { service: 'oidc', serviceName: 'test', secretName: 'test-secret' },
      ];
      const idp = identityProvider(providers);
      expect(idp.isExist()).toBe(true);
    });
  });

  describe('getProviders', () => {
    test('should return empty array for invalid input', () => {
      const idp = identityProvider([] as any);
      expect(idp.getProviders()).toEqual([]);
    });

    test('should return valid OIDC provider', () => {
      const providers: TIdentityProvider[] = [
        { service: 'oidc', serviceName: 'google', secretName: 'google-secret' },
      ];
      const idp = identityProvider(providers);
      expect(idp.getProviders()).toEqual(providers);
    });

    test('should throw error for invalid provider', () => {
      const providers: TIdentityProvider[] = [
        { service: 'invalid', secretName: 'test-secret' },
      ];
      const idp = identityProvider(providers);
      expect(() => idp.getProviders()).toThrow('InvalidSocialProvider');
    });

    test('should throw error for OIDC provider without serviceName', () => {
      const providers: TIdentityProvider[] = [
        { service: 'oidc', secretName: 'test-secret' },
      ];
      const idp = identityProvider(providers);
      expect(() => idp.getProviders()).toThrow('InvalidSocialProvider');
    });

    test('should handle multiple valid providers', () => {
      const providers: TIdentityProvider[] = [
        { service: 'oidc', serviceName: 'google', secretName: 'google-secret' },
        { service: 'oidc', serviceName: 'microsoft', secretName: 'ms-secret' },
      ];
      const idp = identityProvider(providers);
      expect(idp.getProviders()).toEqual(providers);
    });
  });

  describe('getSupportedIndetityProviders', () => {
    test('should include COGNITO provider by default', () => {
      const idp = identityProvider([]);
      const result = idp.getSupportedIndetityProviders();
      expect(result).toContain(
        aws_cognito.UserPoolClientIdentityProvider.COGNITO,
      );
    });

    test('should include custom OIDC provider', () => {
      const providers: TIdentityProvider[] = [
        { service: 'oidc', serviceName: 'google', secretName: 'google-secret' },
      ];
      const idp = identityProvider(providers);
      const result = idp.getSupportedIndetityProviders();

      expect(result).toContain(
        aws_cognito.UserPoolClientIdentityProvider.COGNITO,
      );
      expect(result).toContainEqual(
        aws_cognito.UserPoolClientIdentityProvider.custom('google'),
      );
    });

    test('should throw error for invalid provider', () => {
      const providers: TIdentityProvider[] = [
        { service: 'invalid', serviceName: 'test', secretName: 'test-secret' },
      ];
      const idp = identityProvider(providers);
      expect(() => idp.getSupportedIndetityProviders()).toThrow(
        'InvalidSocialProvider',
      );
    });
  });

  describe('getSocialProviders', () => {
    test('should return empty string for no OIDC providers', () => {
      const idp = identityProvider([]);
      expect(idp.getSocialProviders()).toBe('');
    });

    test('should return empty string for only OIDC providers', () => {
      const providers: TIdentityProvider[] = [
        { service: 'oidc', serviceName: 'google', secretName: 'google-secret' },
      ];
      const idp = identityProvider(providers);
      expect(idp.getSocialProviders()).toBe('');
    });

    test('should return empty string when filtering out OIDC providers', () => {
      const providers: TIdentityProvider[] = [
        { service: 'oidc', serviceName: 'google', secretName: 'google-secret' },
        { service: 'oidc', serviceName: 'microsoft', secretName: 'ms-secret' },
      ];
      const idp = identityProvider(providers);
      expect(idp.getSocialProviders()).toBe('');
    });
  });

  describe('checkCustomProviderEnabled', () => {
    test('should return false when no providers', () => {
      const idp = identityProvider([]);
      expect(idp.checkCustomProviderEnabled()).toBe(false);
    });

    test('should return true when OIDC provider is configured', () => {
      const providers: TIdentityProvider[] = [
        { service: 'oidc', serviceName: 'google', secretName: 'google-secret' },
      ];
      const idp = identityProvider(providers);
      expect(idp.checkCustomProviderEnabled()).toBe(true);
    });

    test('should return false when only non-OIDC providers', () => {
      const providers: TIdentityProvider[] = [];
      const idp = identityProvider(providers);
      expect(idp.checkCustomProviderEnabled()).toBe(false);
    });
  });

  describe('getCustomProviderName', () => {
    test('should return undefined when no providers', () => {
      const idp = identityProvider([]);
      expect(idp.getCustomProviderName()).toBeUndefined();
    });

    test('should return service name when OIDC provider is configured', () => {
      const providers: TIdentityProvider[] = [
        { service: 'oidc', serviceName: 'google', secretName: 'google-secret' },
      ];
      const idp = identityProvider(providers);
      expect(idp.getCustomProviderName()).toBe('google');
    });

    test('should return first OIDC provider name when multiple are configured', () => {
      const providers: TIdentityProvider[] = [
        { service: 'oidc', serviceName: 'google', secretName: 'google-secret' },
        { service: 'oidc', serviceName: 'microsoft', secretName: 'ms-secret' },
      ];
      const idp = identityProvider(providers);
      expect(idp.getCustomProviderName()).toBe('google');
    });
  });

  describe('Complex Scenarios', () => {
    test('should handle mixed valid and invalid providers', () => {
      const providers: TIdentityProvider[] = [
        { service: 'oidc', serviceName: 'google', secretName: 'google-secret' },
        { service: 'invalid', serviceName: 'test', secretName: 'test-secret' },
      ];
      const idp = identityProvider(providers);
      expect(() => idp.getProviders()).toThrow('InvalidSocialProvider');
    });

    test('should handle multiple OIDC providers correctly', () => {
      const providers: TIdentityProvider[] = [
        { service: 'oidc', serviceName: 'google', secretName: 'google-secret' },
        { service: 'oidc', serviceName: 'microsoft', secretName: 'ms-secret' },
        { service: 'oidc', serviceName: 'facebook', secretName: 'fb-secret' },
      ];
      const idp = identityProvider(providers);

      const supportedProviders = idp.getSupportedIndetityProviders();
      expect(supportedProviders).toHaveLength(4);
      expect(supportedProviders).toContainEqual(
        aws_cognito.UserPoolClientIdentityProvider.custom('google'),
      );
      expect(supportedProviders).toContainEqual(
        aws_cognito.UserPoolClientIdentityProvider.custom('microsoft'),
      );
      expect(supportedProviders).toContainEqual(
        aws_cognito.UserPoolClientIdentityProvider.custom('facebook'),
      );
    });

    test('should handle edge case with empty OIDC serviceName', () => {
      const providers: TIdentityProvider[] = [
        { service: 'oidc', serviceName: '', secretName: 'empty-secret' },
      ];
      const idp = identityProvider(providers);
      expect(() => idp.getProviders()).toThrow('InvalidSocialProvider');
    });
  });
});
