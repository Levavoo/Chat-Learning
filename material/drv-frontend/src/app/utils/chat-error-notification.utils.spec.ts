import { HttpErrorResponse } from '@angular/common/http';
import {
  chatConversationLimitNotification,
  chatErrorNotification,
  chatServiceUnavailableNotification,
} from '@models/messages/messages.models';
import { getChatNotification } from './chat-error-notification.utils';

describe('getChatNotification', () => {
  it('should show the conversation limit notice for 409', () => {
    const error = new HttpErrorResponse({
      status: 409,
      error: { error: 'conversation_limit_reached' },
    });

    expect(getChatNotification(error)).toBe(chatConversationLimitNotification);
  });

  it('should show service unavailable for 503 (history read failed)', () => {
    expect(getChatNotification(new HttpErrorResponse({ status: 503 }))).toBe(
      chatServiceUnavailableNotification,
    );
  });

  it('should fall back to the generic error for unknown statuses', () => {
    expect(getChatNotification(new HttpErrorResponse({ status: 418 }))).toBe(
      chatErrorNotification,
    );
  });
});
