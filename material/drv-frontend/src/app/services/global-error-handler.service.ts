import { ErrorHandler, inject, Injectable } from '@angular/core';
import * as StackTrace from 'stacktrace-js';
import { LoggingService } from './logging.service';
import { NotificationService } from '@drv-ds/drv-design-system-ng';
import {
  applicationStateErrorNotification,
  chatErrorNotification,
} from '@models/messages/messages.models';
import { HttpErrorResponse } from '@angular/common/http';
import { LocalNotification } from '@components/feedback/feedback.component';
import { getChatNotification } from '../utils/chat-error-notification.utils';

@Injectable({
  providedIn: 'root',
})
export class GlobalErrorHandlerService implements ErrorHandler {
  loggingService = inject(LoggingService);
  private readonly notificationService = inject(NotificationService);

  handleError(error: unknown): void {
    if (error instanceof HttpErrorResponse) {
      this.handleHttpError(error);
      return;
    }
    this.handleApplicationError(error);
    this.logError(error);
  }

  private handleHttpError(error: HttpErrorResponse) {
    let notification: LocalNotification;
    if (error.url?.includes('/api/chat')) {
      return;
    } else {
      notification = getChatNotification(error);
    }
    this.logError(error, notification);
  }

  private handleApplicationError(error: unknown): void {
    const errorObject =
      error instanceof Error ? error : new Error(String(error));
    StackTrace.fromError(errorObject).then((stackframes) => {
      const stack = stackframes.map((sf) => sf.toString()).join('\n');
      this.loggingService.logError({
        message: error instanceof Error ? error.message : String(error),
        timestamp: new Date().toLocaleTimeString(),
        url: window.location.href,
        userAgent: navigator.userAgent,
        stack,
      });
    });
  }

  private logError(error: unknown, notification?: LocalNotification): void {
    if (
      error instanceof Error &&
      (error.message.includes('ChunkLoadError') ||
        error.message.includes('Loading chunk') ||
        error.message.includes('Failed to fetch dynamically imported module'))
    ) {
      this.notificationService.update(applicationStateErrorNotification);
    } else if (error instanceof HttpErrorResponse && !!notification) {
      this.notificationService.update(notification);
    } else {
      this.notificationService.update(chatErrorNotification);
    }
  }
}
