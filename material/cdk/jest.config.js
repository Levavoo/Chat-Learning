module.exports = {
  testEnvironment: 'node',
  roots: ['<rootDir>/test'],
  testMatch: ['**/*.test.ts'],
  transform: {
    '^.+\\.tsx?$': [
      '@swc/jest',
      {
        jsc: {
          parser: { syntax: 'typescript', tsx: false, decorators: true },
          target: 'es2022',
        },
        module: { type: 'commonjs' },
      },
    ],
  },
  moduleFileExtensions: [
    'ts',
    'tsx',
    'js',
    'jsx',
    'mjs',
    'cjs',
    'mts',
    'cts',
    'json',
    'node',
  ],
  setupFilesAfterEnv: ['<rootDir>/test/setup.ts'],
  maxWorkers: 1,
};
