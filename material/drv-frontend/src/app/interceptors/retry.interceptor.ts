import { HttpErrorResponse, HttpInterceptorFn } from '@angular/common/http';
import { FALLBACK_ERROR_STATUSES } from '@models/messages/messages.models';
import { retry, timer } from 'rxjs';

export const retryInterceptor: HttpInterceptorFn = (req, next) => {
  if (!req.url.includes('/api/chat')) {
    return next(req);
  }

  return next(req).pipe(
    retry({
      count: 3,
      delay: (error, retryCount) => {
        if (
          error instanceof HttpErrorResponse &&
          FALLBACK_ERROR_STATUSES.includes(error.status)
        ) {
          return timer(1000 * Math.pow(2, retryCount - 1));
        }
        throw error;
      },
    }),
  );
};
