import { test, expect } from '@playwright/test';

/**
 * E2E Tests for Bedrock Agent Integration
 *
 * Tests conversation flow, session management, and error handling
 * for the complete chat application with Bedrock backend.
 */
test.describe('Bedrock Agent Integration', () => {
  test.beforeEach(async ({ page }) => {
    // Navigate to chat page and wait for it to load
    await page.goto('/');
    await page.waitForLoadState('networkidle');
  });

  /**
   * AC #1: E2E tests cover conversation flow with Bedrock Agent
   */
  test('should send message and receive response from Bedrock Agent', async ({
    page,
  }) => {
    // Find textarea and send button
    const textarea = page.locator('drv-textarea textarea');
    const sendButton = page.locator('button:has-text("Senden")');

    // Send a simple message
    await textarea.fill('Hallo, kannst du mir helfen?');
    await sendButton.click();

    // Wait for user message to appear
    await expect(page.locator('.message-user').last()).toBeVisible({
      timeout: 5000,
    });

    // Wait for assistant response to appear
    await expect(page.locator('.message-assistant').last()).toBeVisible({
      timeout: 15000,
    });

    // Verify response contains some content
    const responseText = await page
      .locator('.message-assistant')
      .last()
      .textContent();
    expect(responseText).toBeTruthy();
    expect(responseText!.length).toBeGreaterThan(10);
  });

  test('should maintain conversation context across multiple messages', async ({
    page,
  }) => {
    const textarea = page.locator('drv-textarea textarea');
    const sendButton = page.locator('button:has-text("Senden")');

    // First message: Establish context
    await textarea.fill('Mein Lieblingsessen ist Pizza');
    await sendButton.click();
    await expect(page.locator('.message-assistant').last()).toBeVisible({
      timeout: 15000,
    });

    // Clear input and send follow-up
    await textarea.clear();
    await textarea.fill('Was ist mein Lieblingsessen?');
    await sendButton.click();

    // Wait for second response
    const secondResponse = page.locator('.message-assistant').nth(1);
    await expect(secondResponse).toBeVisible({ timeout: 15000 });

    // Verify agent remembers context (case-insensitive check)
    const responseText = await secondResponse.textContent();
    expect(responseText?.toLowerCase()).toContain('pizza');
  });

  test('should handle multi-turn conversation correctly', async ({ page }) => {
    const textarea = page.locator('drv-textarea textarea');
    const sendButton = page.locator('button:has-text("Senden")');

    // Turn 1: Establish first fact
    await textarea.fill('Ich habe einen Hund namens Max');
    await sendButton.click();
    await expect(page.locator('.message-assistant').last()).toBeVisible({
      timeout: 15000,
    });

    // Turn 2: Add second fact
    await textarea.clear();
    await textarea.fill('Max ist 3 Jahre alt');
    await sendButton.click();
    await expect(page.locator('.message-assistant').nth(1)).toBeVisible({
      timeout: 15000,
    });

    // Turn 3: Ask about both facts
    await textarea.clear();
    await textarea.fill('Wie alt ist mein Hund und wie heißt er?');
    await sendButton.click();

    const thirdResponse = page.locator('.message-assistant').nth(2);
    await expect(thirdResponse).toBeVisible({ timeout: 15000 });

    // Verify context from both previous turns
    const responseText =
      (await thirdResponse.textContent())?.toLowerCase() || '';
    expect(responseText).toContain('max');
    expect(responseText).toMatch(/3|drei/);
  });

  /**
   * AC #2: Tests verify session persistence and context continuity
   */
  test('should persist session ID across page refreshes', async ({ page }) => {
    const textarea = page.locator('drv-textarea textarea');
    const sendButton = page.locator('button:has-text("Senden")');

    // Send initial message
    await textarea.fill('Hallo, mein Name ist Test User');
    await sendButton.click();
    await expect(page.locator('.message-assistant').last()).toBeVisible({
      timeout: 15000,
    });

    // Get session ID from localStorage
    const sessionId = await page.evaluate(() =>
      localStorage.getItem('chatbot_session_id'),
    );
    expect(sessionId).toBeTruthy();

    // Refresh page
    await page.reload();
    await page.waitForLoadState('networkidle');

    // Verify session ID persisted
    const sessionIdAfterRefresh = await page.evaluate(() =>
      localStorage.getItem('chatbot_session_id'),
    );
    expect(sessionIdAfterRefresh).toBe(sessionId);

    // Send follow-up message
    const textareaAfterRefresh = page.locator('drv-textarea textarea');
    const sendButtonAfterRefresh = page.locator('button:has-text("Senden")');

    await textareaAfterRefresh.fill('Wie ist mein Name?');
    await sendButtonAfterRefresh.click();

    // Agent should remember from before refresh
    const response = page.locator('.message-assistant').last();
    await expect(response).toBeVisible({ timeout: 15000 });

    const responseText = (await response.textContent())?.toLowerCase() || '';
    expect(responseText).toContain('test');
  });

  test('should verify session ID in localStorage on first load', async ({
    page,
  }) => {
    // Check that session ID is created on page load
    const sessionId = await page.evaluate(() =>
      localStorage.getItem('chatbot_session_id'),
    );
    expect(sessionId).toBeTruthy();
    expect(sessionId).toMatch(
      /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i,
    );
  });

  /**
   * AC #3: Tests verify "new conversation" functionality
   */
  test('should start new conversation with fresh session', async ({ page }) => {
    const textarea = page.locator('drv-textarea textarea');
    const sendButton = page.locator('button:has-text("Senden")');
    const newConversationButton = page.locator(
      'button:has-text("Neues Gespräch")',
    );

    // First conversation
    await textarea.fill('Ich mag Schokolade');
    await sendButton.click();
    await expect(page.locator('.message-assistant').last()).toBeVisible({
      timeout: 15000,
    });

    const firstSessionId = await page.evaluate(() =>
      localStorage.getItem('chatbot_session_id'),
    );

    // Wait for button to be enabled (it's disabled when loading or no messages)
    await expect(newConversationButton).toBeEnabled({ timeout: 5000 });

    // Start new conversation
    await newConversationButton.click();

    const newSessionId = await page.evaluate(() =>
      localStorage.getItem('chatbot_session_id'),
    );
    expect(newSessionId).not.toBe(firstSessionId);

    // Verify conversation history cleared (only welcome message remains if any)
    const messageCount = await page.locator('.message-user').count();
    expect(messageCount).toBe(0);

    // Send message in new conversation
    await textarea.fill('Was mag ich?');
    await sendButton.click();

    // Agent should NOT remember previous conversation
    const response = page.locator('.message-assistant').last();
    await expect(response).toBeVisible({ timeout: 15000 });

    const responseText = (await response.textContent())?.toLowerCase() || '';
    expect(responseText).not.toContain('schokolade');
  });

  /**
   * AC #4: Tests verify error handling for Bedrock failures
   */
  test('should display error notification on backend failure', async ({
    page,
  }) => {
    // Intercept API calls and simulate error
    await page.route('**/api/chat', (route) => {
      route.abort('failed');
    });

    const textarea = page.locator('drv-textarea textarea');
    const sendButton = page.locator('button:has-text("Senden")');

    await textarea.fill('Test message');
    await sendButton.click();

    // Verify error notification appears
    await expect(page.locator('drv-notification').first()).toBeVisible({
      timeout: 5000,
    });
  });

  test('should handle API timeout gracefully', async ({ page }) => {
    // Intercept and delay response to simulate timeout
    await page.route('**/api/chat', async (route) => {
      await new Promise((resolve) => setTimeout(resolve, 35000)); // Longer than timeout
      route.continue();
    });

    const textarea = page.locator('drv-textarea textarea');
    const sendButton = page.locator('button:has-text("Senden")');

    await textarea.fill('Test message');
    await sendButton.click();

    // Should show error or timeout indication
    await expect(page.locator('drv-notification')).toBeVisible({
      timeout: 40000,
    });
  });

  /**
   * AC #5: Tests can run against deployed environment
   */
  test('should include session ID in API requests', async ({ page }) => {
    // Monitor network requests
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

    // Wait a bit for request to be captured
    await page.waitForTimeout(2000);

    // Verify request included session_id
    expect(requests.length).toBeGreaterThan(0);
    expect(requests[0].body).toHaveProperty('conversation_id');
    expect(requests[0].body.conversation_id).toBeTruthy();
  });

  /**
   * AC #6: Test reports show Bedrock-specific metrics
   */
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

    // Verify response within 10 seconds (increased for real API)
    expect(responseTime).toBeLessThan(10000);
  });

  test('should disable send button while message is loading', async ({
    page,
  }) => {
    const textarea = page.locator('drv-textarea textarea');
    const sendButton = page.locator('button:has-text("Senden")');

    await textarea.fill('Test message');
    await sendButton.click();

    // Button should be disabled while loading
    await expect(sendButton).toBeDisabled({ timeout: 1000 });

    // Wait for response
    await expect(page.locator('.message-assistant').last()).toBeVisible({
      timeout: 15000,
    });

    // Button should be enabled again after response
    await expect(sendButton).toBeEnabled({ timeout: 2000 });
  });

  test('should clear input after sending message', async ({ page }) => {
    const textarea = page.locator('drv-textarea textarea');
    const sendButton = page.locator('button:has-text("Senden")');

    await textarea.fill('Test message');
    await sendButton.click();

    // Input should be cleared
    await expect(textarea).toHaveValue('', { timeout: 2000 });
  });

  test('should display example questions on initial load', async ({ page }) => {
    // Check if example questions/linklist is visible
    const linklist = page.locator('drv-linklist');
    await expect(linklist).toBeVisible({ timeout: 5000 });
  });

  test('should hide example questions after first message', async ({
    page,
  }) => {
    const textarea = page.locator('drv-textarea textarea');
    const sendButton = page.locator('button:has-text("Senden")');
    const linklist = page.locator('drv-linklist');

    // Initially visible
    await expect(linklist).toBeVisible({ timeout: 5000 });

    // Send message
    await textarea.fill('Test');
    await sendButton.click();

    // Should be hidden after sending
    await expect(linklist).not.toBeVisible({ timeout: 5000 });
  });
});
