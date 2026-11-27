import { expect, test as setup } from '@playwright/test';
import path from 'path';

const authFileExtern = path.join(__dirname, '.auth/user-extern.json');
const authFileIntern = path.join(__dirname, '.auth/user-intern.json');

setup('authenticate extern user', async ({ page }) => {
  await page.goto('http://localhost:4200/#/login');

  await page
    .getByRole('textbox', {
      name: 'Textfeld zum Eingeben Ihres Benutzernamens',
    })
    .click();
  await page
    .getByRole('textbox', {
      name: 'Textfeld zum Eingeben Ihres Benutzernamens',
    })
    .fill('Testuser@drv-bund.de');
  await page
    .getByRole('textbox', { name: 'Textfeld zum Eingeben Ihres Passworts' })
    .click();
  await page
    .getByRole('textbox', { name: 'Textfeld zum Eingeben Ihres Passworts' })
    .fill('INSERT_PASSWORT_HERE');
  await page.getByRole('button', { name: 'Anmelden' }).click();
  await expect(page.locator('drv-chat-page')).toBeVisible();
  await page.context().storageState({ path: authFileExtern });
});

setup('authenticate intern user', async ({ page }) => {
  await page.goto('http://localhost:4201/#/login');
  await expect(
    page.getByRole('link', { name: 'Deutsche Rentenversicherung' }),
  ).toBeVisible();

  await page
    .getByRole('textbox', {
      name: 'Textfeld zum Eingeben Ihres Benutzernamens',
    })
    .click();
  await page
    .getByRole('textbox', {
      name: 'Textfeld zum Eingeben Ihres Benutzernamens',
    })
    .fill('Testuser@drv-bund.de');
  await page
    .getByRole('textbox', { name: 'Textfeld zum Eingeben Ihres Passworts' })
    .click();
  await page
    .getByRole('textbox', { name: 'Textfeld zum Eingeben Ihres Passworts' })
    .fill('INSERT_PASSWORT_HERE');
  await page.getByRole('button', { name: 'Anmelden' }).click();
  await expect(page.locator('drv-chat-page')).toBeVisible();
  await page.context().storageState({ path: authFileIntern });
});
