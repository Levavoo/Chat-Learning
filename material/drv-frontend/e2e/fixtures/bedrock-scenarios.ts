export interface ConversationMessage {
  user: string;
  expectInResponse: RegExp | string;
}

export interface ConversationScenario {
  name: string;
  description: string;
  messages: ConversationMessage[];
}

export const conversationScenarios: ConversationScenario[] = [
  {
    name: 'Name remembering',
    description: 'Test that agent remembers user name across messages',
    messages: [
      { user: 'Mein Name ist Alice', expectInResponse: /alice/i },
      { user: 'Wie heißt ich?', expectInResponse: /alice/i },
    ],
  },
  {
    name: 'Favorite color',
    description: 'Test that agent remembers stated preferences',
    messages: [
      { user: 'Meine Lieblingsfarbe ist Blau', expectInResponse: /blau/i },
      { user: 'Was ist meine Lieblingsfarbe?', expectInResponse: /blau/i },
    ],
  },
  {
    name: 'Number accumulation',
    description: 'Test that agent can track and calculate across messages',
    messages: [
      { user: 'Ich habe 5 Äpfel', expectInResponse: /5/ },
      { user: 'Ich habe 3 weitere Äpfel gekauft', expectInResponse: /3/ },
      { user: 'Wie viele Äpfel habe ich jetzt?', expectInResponse: /8/ },
    ],
  },
  {
    name: 'Pet information',
    description: 'Test that agent remembers multiple facts about a pet',
    messages: [
      {
        user: 'Ich habe eine Katze namens Whiskers',
        expectInResponse: /whiskers/i,
      },
      { user: 'Whiskers ist 2 Jahre alt', expectInResponse: /2|zwei/i },
      {
        user: 'Wie alt ist meine Katze und wie heißt sie?',
        expectInResponse: /whiskers.*2|2.*whiskers/i,
      },
    ],
  },
  {
    name: 'Travel plans',
    description: 'Test that agent remembers travel information',
    messages: [
      { user: 'Ich plane eine Reise nach Berlin', expectInResponse: /berlin/i },
      { user: 'Ich reise im Juni', expectInResponse: /juni/i },
      {
        user: 'Wohin und wann reise ich?',
        expectInResponse: /berlin.*juni|juni.*berlin/i,
      },
    ],
  },
];

export const errorScenarios = [
  {
    name: 'Network failure',
    description: 'Simulate network error',
    errorType: 'failed' as const,
  },
  {
    name: 'Timeout',
    description: 'Simulate API timeout',
    errorType: 'timedout' as const,
  },
  {
    name: 'Server error',
    description: 'Simulate 500 server error',
    statusCode: 500,
  },
  {
    name: 'Rate limit',
    description: 'Simulate 429 rate limit error',
    statusCode: 429,
  },
];

export const performanceConfig = {
  maxResponseTime: 10000,
  coldStartTime: 15000,
  warmResponseTime: 5000,
};
