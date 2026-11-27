import { LocalNotification } from '@components/feedback/feedback.component';

export interface LogError {
  timestamp: string;
  message: string;
  stack?: string;
  url?: string;
  userAgent: string;
  category?: string;
}

export interface CharError {
  message: string;
  notification: LocalNotification;
  type: string;
}
