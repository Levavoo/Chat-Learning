import { TestBed } from '@angular/core/testing';

import { LoggingService } from './logging.service';
import { LogError } from '@models/common.models';

describe('LoggingService', () => {
  let service: LoggingService;

  beforeEach(() => {
    TestBed.configureTestingModule({});
    service = TestBed.inject(LoggingService);
  });

  it('should be created', () => {
    expect(service).toBeTruthy();
  });

  it('should log error message and end console group', () => {
    const errorSpy = spyOn(console, 'error');
    const groupEndSpy = spyOn(console, 'groupEnd');

    const log: LogError = {
      message: 'Test error',
      timestamp: '10:00:00',
      url: 'http://localhost',
      userAgent: 'Chrome',
      category: 'Runtime',
      stack: 'stack trace',
    };

    service.logError(log);

    expect(errorSpy).toHaveBeenCalledWith('Test error');
    expect(groupEndSpy).toHaveBeenCalled();
  });

  it('should return undefined', () => {
    const result = service.logError({
      message: 'Test error',
      timestamp: '10:00:00',
      url: 'http://localhost',
      userAgent: 'Chrome',
      category: 'Runtime',
      stack: 'stack trace',
    });

    expect(result).toBeUndefined();
  });
});
