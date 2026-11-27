import process from 'node:process';

const API_ENDPOINT = process.env.API_URL || 'http://localhost:8000';

export default [
  {
    context: [
      '/health',
      '/conversation',
      '/conversation/**',
      '/bot',
      '/bot/**',
    ],
    target: API_ENDPOINT,
    secure: false,
    changeOrigin: true,
    logLevel: 'debug',
    headers: {
      'Access-Control-Allow-Origin': '*',
      'Access-Control-Allow-Methods': 'GET, POST, PUT, DELETE, PATCH, OPTIONS',
      'Access-Control-Allow-Headers':
        'Origin, X-Requested-With, Content-Type, Accept, Authorization',
    },
  },
  {
    context: [
      '/api',
      '/api/health',
      '/api/bots',
      '/api/conversation',
      '/api/chat',
      '/api/user',
    ],
    target: API_ENDPOINT,
    secure: false,
    changeOrigin: true,
    logLevel: 'debug',
    headers: {
      'Access-Control-Allow-Origin': '*',
      'Access-Control-Allow-Methods': 'GET, POST, PUT, DELETE, PATCH, OPTIONS',
      'Access-Control-Allow-Headers':
        'Origin, X-Requested-With, Content-Type, Accept, Authorization',
    },
  },
  {
    context: ['/matomo.php'],
    target: 'https://statistik-gsbos.prod.bund.drv/matomo/',
    secure: false,
    changeOrigin: true,
    logLevel: 'debug',
  },
];
