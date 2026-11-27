import { HttpErrorResponse } from '@angular/common/http';
import { LocalNotification } from '@components/feedback/feedback.component';
import {
  chatBlockedNotification,
  chatConversationLimitNotification,
  chatErrorNotification,
  chatNetworkErrorNotification,
  chatRateLimitNotification,
  chatServiceUnavailableNotification,
  chatTechnicalErrorNotification,
  chatTimeoutNotification,
} from '@models/messages/messages.models';

export function getChatNotification(
  error: HttpErrorResponse,
): LocalNotification {
  switch (error.status) {
    case 0:
      return chatNetworkErrorNotification;
    case 403:
      return chatBlockedNotification;
    case 404:
      return chatErrorNotification;
    // Backend: conversation reached MAX_MESSAGES_PER_CONVERSATION (#992).
    case 409:
      return chatConversationLimitNotification;
    case 422:
      return chatErrorNotification;
    case 429:
      return chatRateLimitNotification;
    case 500:
      return chatTechnicalErrorNotification;
    case 503:
      return chatServiceUnavailableNotification;
    case 504:
      return chatTimeoutNotification;
    default:
      return chatErrorNotification;
  }
}
