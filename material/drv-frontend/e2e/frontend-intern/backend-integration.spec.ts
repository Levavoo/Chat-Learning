import { expect, test } from '@playwright/test';

test.describe('Conversation Flow', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/chat');
    await page.waitForLoadState('networkidle');
  });

  test('should send message and receive response', async ({ page }) => {
    const textarea = page.locator('drv-textarea textarea');

    await textarea.fill('Hallo, kannst du mir helfen?');

    const sendButton = page.locator('button:has-text("Senden")');
    await sendButton.click();

    await expect(
      page
        .locator('drv-chat-panel')
        .getByTestId('user-message')
        .getByText('Hallo, kannst du mir helfen?'),
    ).toBeVisible();

    await expect(
      page
        .locator('drv-chat-panel')
        .getByTestId('assistant-message')
        .getByText('Antwort vom Rentenchat:'),
    ).toBeVisible();

    const responseMessage = page
      .locator('drv-chat-panel')
      .getByTestId('assistant-message')
      .last();
    await expect(responseMessage).toBeVisible({
      timeout: 30000,
    });

    const responseText = await responseMessage.textContent();

    expect(responseText).toBeTruthy();
    expect(responseText!.length).toBeGreaterThan(24);
    expect(responseText).toContain(
      'Diese Antwort ist KI-generiert und nicht rechtsverbindlich.',
    );
  });

  test('should maintain conversation context across multiple messages', async ({
    page,
  }) => {
    const textarea = page.locator('drv-textarea textarea');
    await textarea.fill(
      'Mein Lieblingsessen ist Pizza. Nimm das nur zur Kenntnis und antworte entsprechend kurz.',
    );

    const sendButton = page.locator('button:has-text("Senden")');
    await sendButton.click();

    const firstResponse = page
      .locator('drv-chat-panel')
      .getByTestId('assistant-message')
      .nth(1);

    await expect(firstResponse).toBeVisible({
      timeout: 30000,
    });

    await textarea.clear();
    await textarea.fill(
      'Was ist mein Lieblingsessen? Antworte so knapp wie möglich.',
    );
    await sendButton.click();

    const secondResponse = page
      .locator('drv-chat-panel')
      .getByTestId('assistant-message')
      .nth(2);

    await expect(secondResponse).toBeVisible({
      timeout: 30000,
    });

    const responseText = await secondResponse.textContent();
    await expect(responseText?.toLowerCase()).toContain('pizza');
  });

  test('should handle multi-turn conversation correctly', async ({ page }) => {
    const textarea = page.locator('drv-textarea textarea');
    await textarea.fill('Ich habe einen Hund namens Max');

    const sendButton = page.locator('button:has-text("Senden")');
    await sendButton.click();

    const firstResponse = page
      .locator('drv-chat-panel')
      .getByTestId('assistant-message')
      .nth(1);

    await expect(firstResponse).toBeVisible({
      timeout: 30000,
    });

    await textarea.clear();
    await textarea.fill('Max ist 3 Jahre alt');
    await sendButton.click();

    const secondResponse = page
      .locator('drv-chat-panel')
      .getByTestId('assistant-message')
      .nth(2);

    await expect(secondResponse).toBeVisible({
      timeout: 30000,
    });

    await textarea.clear();
    await textarea.fill('Wie alt ist mein Hund und wie heißt er?');
    await sendButton.click();

    const thirdResponse = page
      .locator('drv-chat-panel')
      .getByTestId('assistant-message')
      .nth(3);
    await expect(thirdResponse).toBeVisible({ timeout: 30000 });

    const responseText =
      (await thirdResponse.textContent())?.toLowerCase() || '';
    expect(responseText).toContain('max');
    expect(responseText).toMatch(/3|drei/);
  });

  test('should handle logical questions', async ({ page }) => {
    const textarea = page.locator('drv-textarea textarea');
    await textarea.fill(
      'Ein Handtuch braucht 7 Minuten zum trocknen. Nehme dies erstmal nur zu Kenntnis und antworte so knapp wie möglich.',
    );

    const sendButton = page.locator('button:has-text("Senden")');
    await sendButton.click();

    const firstResponse = page
      .locator('drv-chat-panel')
      .getByTestId('assistant-message')
      .nth(1);

    await expect(firstResponse).toBeVisible({
      timeout: 30000,
    });

    await textarea.clear();
    await textarea.fill(
      'Wie viele Minuten brauchen 4 Handtücher zum trocknen? Antworte so knapp wie möglich.',
    );
    await sendButton.click();

    const secondResponse = page
      .locator('drv-chat-panel')
      .getByTestId('assistant-message')
      .nth(2);

    await expect(secondResponse).toBeVisible({
      timeout: 30000,
    });

    const responseText = await secondResponse.textContent();
    await expect(responseText?.toLowerCase()).toContain('7');
  });
});

test.describe('Session persistence', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/chat');
    await page.waitForLoadState('networkidle');
  });

  test('should persist session ID across page refreshes', async ({ page }) => {
    const textarea = page.locator('drv-textarea textarea');
    const sendButton = page.locator('button:has-text("Senden")');

    await textarea.fill('Hallo, mein Name ist Test User');
    await sendButton.click();
    await expect(page.locator('.message-assistant').last()).toBeVisible({
      timeout: 30000,
    });

    const sessionId = await page.evaluate(() =>
      localStorage.getItem('chatbot_session_id'),
    );
    expect(sessionId).toBeTruthy();

    await page.reload();
    await page.waitForLoadState('networkidle');

    const sessionIdAfterRefresh = await page.evaluate(() =>
      localStorage.getItem('chatbot_session_id'),
    );
    expect(sessionIdAfterRefresh).toBe(sessionId);

    const textareaAfterRefresh = page.locator('drv-textarea textarea');
    const sendButtonAfterRefresh = page.locator('button:has-text("Senden")');

    await textareaAfterRefresh.fill('Wie ist mein Name?');
    await sendButtonAfterRefresh.click();

    const response = page.locator('.message-assistant').last();
    await expect(response).toBeVisible({ timeout: 30000 });

    const responseText = (await response.textContent())?.toLowerCase() || '';
    expect(responseText).toContain('test');
  });

  test('should verify session ID in localStorage on first load', async ({
    page,
  }) => {
    const sessionId = await page.evaluate(() =>
      localStorage.getItem('chatbot_session_id'),
    );
    expect(sessionId).toBeTruthy();
    expect(sessionId).toMatch(
      /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i,
    );
  });
});

test.describe('Conversation', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/chat');
    await page.waitForLoadState('networkidle');
  });

  test('should copy conversationId', async ({ page }) => {
    await expect(
      page.getByRole('button', { name: 'Kopiere ID' }),
    ).not.toBeVisible();

    await page
      .getByRole('textbox', { name: 'Nachricht an den Rentenchat' })
      .click();
    await page
      .getByRole('textbox', { name: 'Nachricht an den Rentenchat' })
      .fill('Dies ist ein Test. Antworte nur ganz kurz mit einem Punkt.');
    await page.getByRole('button', { name: 'Senden' }).click();
    await expect(
      page.getByRole('button', { name: 'Kopiere ID' }),
    ).toBeVisible();
    await page.getByRole('button', { name: 'Kopiere ID' }).click();
  });

  test('should start new conversation with fresh session', async ({ page }) => {
    const textarea = page.locator('drv-textarea textarea');
    const sendButton = page.locator('button:has-text("Senden")');
    const newConversationButton = page.locator(
      'button:has-text("Neues Gespräch")',
    );

    await textarea.fill('Ich mag Schokolade');
    await sendButton.click();
    await expect(page.locator('.message-assistant').last()).toBeVisible({
      timeout: 15000,
    });

    const firstSessionId = await page.evaluate(() =>
      localStorage.getItem('chatbot_session_id'),
    );

    await expect(newConversationButton).toBeEnabled({ timeout: 5000 });

    await newConversationButton.click();

    const newSessionId = await page.evaluate(() =>
      localStorage.getItem('chatbot_session_id'),
    );
    expect(newSessionId).not.toBe(firstSessionId);

    const messageCount = await page.locator('.message-user').count();
    expect(messageCount).toBe(0);

    await textarea.fill('Was mag ich?');
    await sendButton.click();

    const response = page.locator('.message-assistant').last();
    await expect(response).toBeVisible({ timeout: 15000 });

    const responseText = (await response.textContent())?.toLowerCase() || '';
    expect(responseText).not.toContain('schokolade');
  });
});

test.describe('Error handling', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/chat');
    await page.waitForLoadState('networkidle');
  });

  test('should display error notification on backend failure', async ({
    page,
  }) => {
    await page.route('**/api/chat', (route) => {
      route.abort('failed');
    });

    const textarea = page.locator('drv-textarea textarea');
    const sendButton = page.locator('button:has-text("Senden")');

    await textarea.fill('Test message');
    await sendButton.click();

    await expect(page.locator('drv-notification').first()).toBeVisible({
      timeout: 5000,
    });
  });

  test('should handle API timeout gracefully', async ({ page }) => {
    await page.route('**/api/chat', async (route) => {
      await new Promise((resolve) => setTimeout(resolve, 35000)); // Longer than timeout
      route.continue();
    });

    const textarea = page.locator('drv-textarea textarea');
    const sendButton = page.locator('button:has-text("Senden")');

    await textarea.fill('Test message');
    await sendButton.click();

    await expect(page.locator('drv-notification')).toBeVisible({
      timeout: 40000,
    });
  });
});

test.describe('Bedrock-specific metrics', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/chat');
    await page.waitForLoadState('networkidle');
  });

  test('should respond within acceptable time limit', async ({ page }) => {
    const textarea = page.locator('drv-textarea textarea');
    const sendButton = page.locator('button:has-text("Senden")');

    await textarea.fill('Hallo, wie geht es dir?');

    const startTime = Date.now();
    await sendButton.click();
    await expect(page.locator('.message-assistant').last()).toBeVisible({
      timeout: 15000,
    });
    const endTime = Date.now();

    const responseTime = endTime - startTime;

    expect(responseTime).toBeLessThan(10000);
  });

  test('should disable send button while message is loading', async ({
    page,
  }) => {
    const textarea = page.locator('drv-textarea textarea');
    const sendButton = page.locator('button:has-text("Senden")');

    await textarea.fill('Test message');
    await sendButton.click();

    await expect(sendButton).toBeDisabled({ timeout: 1000 });

    await expect(page.locator('.message-assistant').last()).toBeVisible({
      timeout: 15000,
    });

    await expect(sendButton).toBeEnabled({ timeout: 2000 });
  });

  test('should clear input after sending message', async ({ page }) => {
    const textarea = page.locator('drv-textarea textarea');
    const sendButton = page.locator('button:has-text("Senden")');

    await textarea.fill('Test message');
    await sendButton.click();

    await expect(textarea).toHaveValue('', { timeout: 2000 });
  });

  test('should display example questions on initial load', async ({ page }) => {
    const linklist = page.locator('drv-linklist');
    await expect(linklist).toBeVisible({ timeout: 5000 });
  });

  test('should hide example questions after first message', async ({
    page,
  }) => {
    const textarea = page.locator('drv-textarea textarea');
    const sendButton = page.locator('button:has-text("Senden")');
    const linklist = page.locator('drv-linklist');

    await expect(linklist).toBeVisible({ timeout: 5000 });

    await textarea.fill('Test');
    await sendButton.click();

    await expect(linklist).not.toBeVisible({ timeout: 5000 });
  });
});

test('should include session ID in API requests', async ({ page }) => {
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
          });
        } catch (e) {
          // Ignore JSON parse errors
        }
      }
    }
  });

  const textarea = page.locator('drv-textarea textarea');
  const sendButton = page.locator('button:has-text("Senden")');

  await textarea.fill('Test');
  await sendButton.click();

  await page.waitForTimeout(2000);

  expect(requests.length).toBeGreaterThan(0);
  expect(requests[0].body).toHaveProperty('conversation_id');
  expect(requests[0].body.conversation_id).toBeTruthy();
});

test('should send Feedback', async ({ page }) => {
  await page.goto('/chat');

  const feedbackButton = page.getByRole('button', { name: 'Feedback' });

  await expect(feedbackButton).toBeDisabled();

  await page
    .getByRole('textbox', { name: 'Nachricht an den Rentenchat' })
    .click();
  await page
    .getByRole('textbox', { name: 'Nachricht an den Rentenchat' })
    .fill('Dies ist eine Testnachricht. Antworte wenn möglich nur ganz kurz.');

  await page.getByRole('button', { name: 'Senden' }).click();

  await expect(feedbackButton).toBeEnabled({ timeout: 30000 });
  await feedbackButton.click();

  await expect(page.locator('div[class=panel]')).toBeVisible();

  await expect(
    page
      .getByLabel('Feedback zur Konversation')
      .getByRole('button', { name: 'Senden' }),
  ).toBeDisabled();

  await page.getByTestId('Vergleichbarkeit').getByLabel('Ja').check();
  await page.getByTestId('Vergleichbarkeit').getByLabel('Nein').check();

  await page.getByTestId('Qualität').getByLabel('Nein').check();
  await page.getByTestId('Qualität').getByLabel('Ja').check();

  await page.getByTestId('Vollständigkeit').getByLabel('Ja').check();
  await page.getByTestId('Vollständigkeit').getByLabel('Nein').check();

  await page.getByTestId('Tonalität').getByLabel('Nein').check();
  await page.getByTestId('Tonalität').getByLabel('Ja').check();

  await page.getByTestId('Länge').getByLabel('Ja').check();
  await page.getByTestId('Länge').getByLabel('Nein').check();

  await page.getByTestId('Korrektheit').getByLabel('Nein').check();
  await page.getByTestId('Korrektheit').getByLabel('Ja').check();

  await expect(
    page.getByRole('textbox', { name: 'Optional: Haben Sie' }),
  ).toBeVisible();
  await page.getByRole('textbox', { name: 'Optional: Haben Sie' }).click();
  await page
    .getByRole('textbox', { name: 'Optional: Haben Sie' })
    .fill('Dies ist ein Playwright-Test');

  expect(
    page.getByTestId('Vergleichbarkeit').locator('input[value="Ja"]'),
  ).not.toBeChecked();
  expect(
    page.getByTestId('Vergleichbarkeit').locator('input[value="Nein"]'),
  ).toBeChecked();

  expect(
    page.getByTestId('Qualität').locator('input[value="Ja"]'),
  ).toBeChecked();
  expect(
    page.getByTestId('Qualität').locator('input[value="Nein"]'),
  ).not.toBeChecked();

  expect(
    page.getByTestId('Vollständigkeit').locator('input[value="Ja"]'),
  ).not.toBeChecked();
  expect(
    page.getByTestId('Vollständigkeit').locator('input[value="Nein"]'),
  ).toBeChecked();

  expect(
    page.getByTestId('Tonalität').locator('input[value="Ja"]'),
  ).toBeChecked();
  expect(
    page.getByTestId('Tonalität').locator('input[value="Nein"]'),
  ).not.toBeChecked();

  expect(
    page.getByTestId('Länge').locator('input[value="Ja"]'),
  ).not.toBeChecked();
  expect(
    page.getByTestId('Länge').locator('input[value="Nein"]'),
  ).toBeChecked();

  expect(
    page.getByTestId('Korrektheit').locator('input[value="Ja"]'),
  ).toBeChecked();
  expect(
    page.getByTestId('Korrektheit').locator('input[value="Nein"]'),
  ).not.toBeChecked();

  await expect(
    page
      .getByLabel('Feedback zur Konversation')
      .getByRole('button', { name: 'Senden' }),
  ).toBeEnabled();
  await page
    .getByTestId('submitFeedback')
    .getByRole('button', { name: 'Senden' })
    .click();

  await expect(page.getByText('Feedback erfolgreich versendet')).toBeVisible();
});
