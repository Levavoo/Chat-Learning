import { Page, expect } from '@playwright/test';

export async function sendMessage(page: Page, message: string): Promise<void> {
  const textarea = page.locator('drv-textarea textarea');
  const sendButton = page.locator('button:has-text("Senden")');

  await textarea.fill(message);
  await sendButton.click();
}

export async function waitForAssistantResponse(
  page: Page,
  index: number = -1,
  timeout: number = 15000,
): Promise<string> {
  const selector =
    index === -1
      ? '.message-assistant'
      : `.message-assistant:nth-child(${index + 1})`;

  const messageLocator = page.locator(selector).last();
  await expect(messageLocator).toBeVisible({ timeout });

  const text = await messageLocator.textContent();
  return text || '';
}

export async function getSessionId(page: Page): Promise<string | null> {
  return await page.evaluate(() => localStorage.getItem('chatbot_session_id'));
}

export async function clearSessionAndReload(page: Page): Promise<void> {
  await page.evaluate(() => {
    localStorage.removeItem('chatbot_session_id');
  });
  await page.reload();
  await page.waitForLoadState('networkidle');
}

export async function startNewConversation(page: Page): Promise<void> {
  const newConversationButton = page.locator(
    'button:has-text("Neues Gespräch")',
  );
  await expect(newConversationButton).toBeEnabled({ timeout: 5000 });
  await newConversationButton.click();
}

export async function countMessages(
  page: Page,
  type: 'user' | 'assistant' | 'all',
): Promise<number> {
  let selector = '.message';
  if (type === 'user') selector = '.message-user';
  if (type === 'assistant') selector = '.message-assistant';

  return await page.locator(selector).count();
}

export async function verifyResponseContains(
  page: Page,
  expectedText: string | RegExp,
  index: number = -1,
): Promise<void> {
  const response = await waitForAssistantResponse(page, index);

  if (typeof expectedText === 'string') {
    expect(response.toLowerCase()).toContain(expectedText.toLowerCase());
  } else {
    expect(response).toMatch(expectedText);
  }
}

export async function waitForChatReady(page: Page): Promise<void> {
  await page.waitForLoadState('networkidle');
  const textarea = page.locator('drv-textarea textarea');
  await expect(textarea).toBeVisible({ timeout: 5000 });
}

export async function interceptChatApi(
  page: Page,
  handler: (route: any) => void,
): Promise<void> {
  await page.route('**/api/chat', handler);
}

export function monitorApiRequests(page: Page): any[] {
  const requests: any[] = [];

  page.on('request', (request) => {
    if (request.url().includes('/api/chat')) {
      const postData = request.postData();
      if (postData) {
        try {
          requests.push({
            url: request.url(),
            method: request.method(),
            body: JSON.parse(postData),
            timestamp: Date.now(),
          });
        } catch (e) {
          // JSON parse errors are expected for non-JSON bodies.
        }
      }
    }
  });

  return requests;
}

export async function measureResponseTime(
  page: Page,
  message: string,
): Promise<number> {
  const startTime = Date.now();
  await sendMessage(page, message);
  await waitForAssistantResponse(page);
  return Date.now() - startTime;
}
