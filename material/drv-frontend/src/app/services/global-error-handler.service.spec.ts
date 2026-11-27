import { TestBed } from '@angular/core/testing';

import { GlobalErrorHandlerService } from './global-error-handler.service';
import { LoggingService } from '../services/logging.service';
import { NotificationService } from '@drv-ds/drv-design-system-ng';
import {
  applicationStateErrorNotification,
  chatBlockedNotification,
  chatErrorNotification,
  chatNetworkErrorNotification,
  chatRateLimitNotification,
  chatServiceUnavailableNotification,
  chatTimeoutNotification,
} from '@models/messages/messages.models';
import { HttpErrorResponse } from '@angular/common/http';

describe('GlobalErrorHandlerService', () => {
  let service: GlobalErrorHandlerService;
  let loggingService: jasmine.SpyObj<LoggingService>;
  let notificationService: jasmine.SpyObj<NotificationService>;

  beforeEach(() => {
    loggingService = jasmine.createSpyObj('LoggingService', ['logError']);
    notificationService = jasmine.createSpyObj('NotificationService', [
      'update',
    ]);

    TestBed.configureTestingModule({
      providers: [
        GlobalErrorHandlerService,
        {
          provide: LoggingService,
          useValue: loggingService,
        },
        {
          provide: NotificationService,
          useValue: notificationService,
        },
      ],
    });

    service = TestBed.inject(GlobalErrorHandlerService);
  });

  afterEach(() => {
    jasmine.clock().uninstall();
  });

  it('should be created', () => {
    expect(service).toBeTruthy();
  });
  describe('GlobalErrorHandlerService notification handling', () => {
    it('should show applicationStateErrorNotification for ChunkLoadError', () => {
      service.handleError(new Error('ChunkLoadError'));

      expect(notificationService.update).toHaveBeenCalledWith(
        applicationStateErrorNotification,
      );
    });

    it('should show applicationStateErrorNotification for Loading chunk error', () => {
      service.handleError(new Error('Loading chunk 123 failed'));

      expect(notificationService.update).toHaveBeenCalledWith(
        applicationStateErrorNotification,
      );
    });

    it('should show applicationStateErrorNotification for dynamic import error', () => {
      service.handleError(
        new Error('Failed to fetch dynamically imported module'),
      );

      expect(notificationService.update).toHaveBeenCalledWith(
        applicationStateErrorNotification,
      );
    });

    it('should show chatErrorNotification for other errors', () => {
      service.handleError(new Error('Unexpected error'));

      expect(notificationService.update).toHaveBeenCalledWith(
        chatErrorNotification,
      );
    });
    [
      { status: 0, notification: chatNetworkErrorNotification },
      { status: 403, notification: chatBlockedNotification },
      { status: 429, notification: chatRateLimitNotification },
      { status: 503, notification: chatServiceUnavailableNotification },
      { status: 504, notification: chatTimeoutNotification },
    ].forEach(({ status, notification }) => {
      it(`should show correct notification for HTTP ${status}`, () => {
        const error = new HttpErrorResponse({ status });

        service.handleError(error);

        expect(notificationService.update).toHaveBeenCalledWith(notification);
      });
    });
  });
});
