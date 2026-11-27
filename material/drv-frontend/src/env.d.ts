declare interface Env {
  readonly NG_APP_API_ENDPOINT: string;
  readonly NG_APP_USER_POOL_ID: string;
  readonly NG_APP_USER_POOL_CLIENT_ID: string;
  readonly NG_APP_REGION: string;
  readonly NG_APP_REDIRECT_SIGNIN_URL: string;
  readonly NG_APP_REDIRECT_SIGNOUT_URL: string;
  readonly NG_APP_COGNITO_DOMAIN: string;
  readonly NG_APP_ANONYMOUS_ACCESS: string;
  readonly NG_APP_INTERN: string;
  readonly NG_APP_SHOW_REVIEW_TAG?: string;
}

declare interface ImportMeta {
  readonly env: Env;
}
