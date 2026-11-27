import { LinklistData } from '@drv-ds/drv-design-system-ng';

export enum ExampleQuestionCategory {
  Rente,
  Reha,
  Versicherung,
  Sonstiges,
}
export interface ExampleQuestionLinklistData extends LinklistData {
  category: ExampleQuestionCategory;
  faqUrl?: string;
  answerUrl?: string;
  additionalInfos?: string;
}
