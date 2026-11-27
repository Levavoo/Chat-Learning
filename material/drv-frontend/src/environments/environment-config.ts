export interface EnvironmentConfig {
  apiEndpoint?: string;
  userPoolId: string;
  userPoolClientId: string;
  region: string;
  redirectSigninUrl?: string;
  redirectSignoutUrl?: string;
  cognitoDomain?: string;
  anonymousAccess: boolean;
  intern: boolean;
}
