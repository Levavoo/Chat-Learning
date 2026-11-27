import { devices } from '@playwright/test';

export function chromiumSmokeProject(name: string) {
  const chromeBin = process.env.CHROME_BIN;
  if (!chromeBin) {
    throw new Error(
      'CHROME_BIN must point to the existing Chromium binary; browser downloads are disabled for this smoke test',
    );
  }

  return {
    name,
    use: {
      ...devices['Desktop Chrome'],
      launchOptions: {
        executablePath: chromeBin,
        args: [
          '--no-sandbox',
          '--disable-setuid-sandbox',
          '--disable-dev-shm-usage',
          '--disable-gpu',
        ],
      },
    },
  };
}
