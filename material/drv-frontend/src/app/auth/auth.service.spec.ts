import {} from 'jasmine';

import { isUserUnauthenticatedError } from './auth.service';

describe('isUserUnauthenticatedError', () => {
  it('recognizes Amplify UserUnAuthenticatedException errors', () => {
    const error = new Error('User needs to be authenticated to call this API.');
    error.name = 'UserUnAuthenticatedException';

    expect(isUserUnauthenticatedError(error)).toBeTrue();
    expect(
      isUserUnauthenticatedError({ name: 'UserUnAuthenticatedException' }),
    ).toBeTrue();
  });

  it('does not hide unexpected authentication failures', () => {
    expect(
      isUserUnauthenticatedError(new Error('network unavailable')),
    ).toBeFalse();
    expect(
      isUserUnauthenticatedError({ name: 'UnknownException' }),
    ).toBeFalse();
    expect(isUserUnauthenticatedError(null)).toBeFalse();
  });
});
