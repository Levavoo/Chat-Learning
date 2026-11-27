export const environment = {
  name: 'prod',
  intern: import.meta.env?.NG_APP_INTERN === 'true',
  skipAuth: import.meta.env?.NG_APP_ANONYMOUS_ACCESS === 'true',
  showReviewTag: import.meta.env?.NG_APP_SHOW_REVIEW_TAG === 'true',
};
