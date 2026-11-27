import { Injectable } from '@angular/core';
import { LogError } from '@models/common.models';

@Injectable({
  providedIn: 'root',
})
export class LoggingService {
  logError(log: LogError): unknown {
    console.error(log.message);
    console.groupEnd();
    return;
  }
}
