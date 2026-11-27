import type { MessageFeedback } from '../../types';

// Mirrors `_LikertRating` / `_ComparabilityRating` in backend_orchestrator/models/api_models.py.
// Radio-group form controls hold `Rating[]`; the service pulls `[0]` to post the scalar.
export const likertRating = [
  'Yes',
  'Likely yes',
  'Probably not',
  'No',
  'Cannot evaluate',
] as const;
export type LikertRating = (typeof likertRating)[number];

export const comparabilityRating = [
  'Better',
  'Equally good',
  'Equally bad',
  'Worse',
  'Cannot evaluate',
] as const;
export type ComparabilityRating = (typeof comparabilityRating)[number];

// Mirrors `_UsedScenario` in backend_orchestrator/models/api_models.py.
export type UsedScenario = 0 | 1 | 2 | 3 | 4 | 5 | 6;

// Legacy alias for template-level `*ngFor` over the full set; prefer `likertRating` / `comparabilityRating` in new code.
export const rating = [...likertRating, ...comparabilityRating] as const;
export type Rating = LikertRating | ComparabilityRating;

export enum UserFeedback {
  Good = 'GOOD',
  Neutral = 'NEUTRAL',
  Bad = 'BAD',
}

export interface FeedbackType {
  messageId?: string;
  value?: UserFeedback;
  type?: string;
}
export const feedbackModalId = 'feedbackModal';

export interface RawFeedbackRating {
  isMultiturn: boolean;
  isSingleturn: boolean;
  isFreeUserTest: boolean;
  isFinalFeedback: boolean;
  isPerTurnFeedback: boolean;
  producer?: MessageFeedback['producer'];
  scope?: MessageFeedback['scope'];
  technicalCorrectivity?: LikertRating[];
  coverageLevel?: LikertRating[];
  comprehensibility?: LikertRating[];
  precision?: LikertRating[];
  tonality?: LikertRating[];
  utilityValue?: string[];
  comparabilityToGoogleAi?: ComparabilityRating[];
  sourceMatching?: LikertRating[];
  sourceQuality?: LikertRating[];
  usedScenario?: UsedScenario[];
  goalAchievement?: LikertRating[];
  dialogueSkills?: LikertRating[];
  handlingCorrections?: LikertRating[];
  furtherDevelopment?: string[];
  goodToRecommend?: LikertRating[];
  comment?: string;
  helpfulness?: UserFeedback;
}
