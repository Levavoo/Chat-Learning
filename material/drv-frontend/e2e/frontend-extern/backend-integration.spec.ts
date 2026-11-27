import { expect, test } from '@playwright/test';

test.describe('Disclaimer', () => {
  test('accept over Checkbox', async ({ page }) => {
    await page.goto('/chat');
    await expect(page.getByText('Ich akzeptiere und nehme die')).toBeVisible();

    const checkbox = page.locator('drv-checkbox[name="disclaimer-checkbox"]');
    await expect(checkbox).toBeVisible();

    await expect(page.getByTestId('exampleQuestions')).not.toBeVisible();

    await expect(
      page.getByRole('textbox', { name: 'Nachricht an den Rentenchat' }),
    ).not.toBeVisible();

    await checkbox.locator('input[type=checkbox]').click();
    await expect(checkbox).not.toBeVisible();

    await expect(page.getByTestId('exampleQuestions')).toBeVisible();

    await expect(
      page.getByRole('textbox', { name: 'Nachricht an den Rentenchat' }),
    ).toBeVisible();
  });

  test('accept over Disclaimerpage', async ({ page }) => {
    await page.goto('/chat');
    await expect(page.getByText('Ich akzeptiere und nehme die')).toBeVisible();
    await page.getByRole('link', { name: 'Nutzungsbedingungen und' }).click();
    await expect(
      page
        .locator('div')
        .filter({ hasText: 'Haftungsauschluss / Hinweis' })
        .nth(3),
    ).toBeVisible();
    await expect(
      page.getByRole('button', { name: 'Akzeptieren' }),
    ).toBeVisible();
    await page.getByRole('button', { name: 'Akzeptieren' }).click();
    await expect(
      page.getByRole('textbox', { name: 'Nachricht an den Rentenchat' }),
    ).toBeVisible();
  });
});

test.describe('Buttons', () => {
  test('open "Nutzungshilfe"', async ({ page }) => {
    await page.goto('/chat');
    await expect(page.getByRole('button', { name: 'Hilfe' })).toBeVisible();
    await page.getByRole('button', { name: 'Hilfe' }).click();
    await expect(page.locator('drv-modal-content')).toContainText(
      'Nutzungshilfe',
    );
    await expect(page.getByRole('button', { name: 'Schließen' })).toBeVisible();
    await page.getByRole('button', { name: 'Schließen' }).click();
  });

  test('open PrintPage', async ({ page }) => {
    await page.goto('/chat');

    await page.evaluate(() => {
      window.print = () => {
        (window as any).__printCalled = true;
      };
    });

    await expect(page.getByRole('button', { name: 'Drucken' })).toBeVisible();
    await page.getByRole('button', { name: 'Drucken' }).click();

    const wasCalled = await page.evaluate(() => (window as any).__printCalled);

    expect(wasCalled).toBe(true);
  });
});

test.describe('Chat', () => {
  test('should be named Renate', async ({ page }) => {
    await page.goto('/chat');

    const checkbox = page.locator('drv-checkbox[name="disclaimer-checkbox"]');
    await checkbox.locator('input[type=checkbox]').click();

    await page
      .getByRole('textbox', { name: 'Nachricht an den Rentenchat' })
      .click();
    await page
      .getByRole('textbox', { name: 'Nachricht an den Rentenchat' })
      .fill('Wie heißt du?');
    await page.getByRole('button', { name: 'Senden' }).click();

    const responseMessage = page
      .locator('drv-chat-panel')
      .getByTestId('assistant-message')
      .nth(1);
    await expect(responseMessage).toBeVisible({
      timeout: 20000,
    });

    const responseText = await responseMessage.textContent();

    expect(responseText?.toLowerCase()).toContain('renate');
  });

  test('should show clickable examplequestions', async ({ page }) => {
    await page.goto('/chat');

    const checkbox = page.locator('drv-checkbox[name="disclaimer-checkbox"]');
    await checkbox.locator('input[type=checkbox]').click();

    const exampleQuestions = page.getByTestId('exampleQuestions');

    await expect(exampleQuestions).toBeVisible();

    const firstQuestion = exampleQuestions.getByRole('button').first();
    const firstQuestionText = (await firstQuestion.textContent()) as string;

    await firstQuestion.click();

    await expect(
      page.getByTestId('user-message').getByText(firstQuestionText),
    ).toBeVisible();

    await expect(exampleQuestions).not.toBeVisible();

    const responseMessage = page
      .locator('drv-chat-panel')
      .getByTestId('assistant-message')
      .nth(1);
    await expect(responseMessage).toBeVisible({
      timeout: 20000,
    });
  });
});
