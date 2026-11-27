import { HttpClient, HttpHeaders } from '@angular/common/http';
import { inject, Injectable } from '@angular/core';
import { MessageFeedback } from '@models/bedrock-chat.models';
import { RawFeedbackRating } from '@models/feedback/feedback.model';
import { ApiProxyService } from '@services/api-proxy/api-proxy.service';
import { Observable } from 'rxjs';

@Injectable({
  providedIn: 'root',
})
export class FeedbackService {
  private readonly http = inject(HttpClient);
  private readonly apiProxyService = inject(ApiProxyService);

  rawFeedbackRating: RawFeedbackRating = {
    isMultiturn: false,
    isSingleturn: false,
    isFreeUserTest: false,
    isFinalFeedback: false,
    isPerTurnFeedback: false,
  };

  public saveFeedback(
    feedback: MessageFeedback,
    sessionId: string,
    messageId: string,
  ): Observable<{ success: boolean }> {
    const feedbackUrl = `${this.apiProxyService.conversationUrl}/${sessionId}/feedback`;
    return this.http.put<{ success: boolean }>(
      feedbackUrl,
      { messageId, ...feedback },
      {
        headers: new HttpHeaders({
          'Content-Type': 'application/json',
        }),
      },
    );
  }

  createFeedbackRating(rating: RawFeedbackRating): MessageFeedback {
    return {
      isMultiturn: rating.isMultiturn,
      isSingleturn: rating.isSingleturn,
      isFreeUserTest: rating.isFreeUserTest,
      isFinalFeedback: rating.isFinalFeedback,
      isPerTurnFeedback: rating.isPerTurnFeedback,
      technicalCorrectivity: rating.technicalCorrectivity
        ? rating.technicalCorrectivity[0]
        : null,
      coverageLevel: rating.coverageLevel ? rating.coverageLevel[0] : null,
      comprehensibility: rating.comprehensibility
        ? rating.comprehensibility[0]
        : null,
      tonality: rating.tonality ? rating.tonality[0] : null,
      utilityValue: rating.utilityValue ? rating.utilityValue[0] : null,
      comparabilityToGoogleAi: rating.comparabilityToGoogleAi
        ? rating.comparabilityToGoogleAi[0]
        : null,
      sourceMatching: rating.sourceMatching ? rating.sourceMatching[0] : null,
      sourceQuality: rating.sourceQuality ? rating.sourceQuality[0] : null,
      usedScenario:
        rating.usedScenario && rating.usedScenario.length > 0
          ? rating.usedScenario[0]
          : null,
      goalAchievement: rating.goalAchievement
        ? rating.goalAchievement[0]
        : null,
      dialogueSkills: rating.dialogueSkills ? rating.dialogueSkills[0] : null,
      handlingCorrections: rating.handlingCorrections
        ? rating.handlingCorrections[0]
        : null,
      furtherDevelopment: rating.furtherDevelopment
        ? rating.furtherDevelopment[0]
        : null,
      goodToRecommend: rating.goodToRecommend
        ? rating.goodToRecommend[0]
        : null,
      precision: rating.precision ? rating.precision[0] : null,
      comment: rating.comment ?? null,
      helpfulness: rating.helpfulness ? rating.helpfulness : null,
      producer: rating.producer ?? null,
      scope: rating.scope ?? null,
      technicalCorrectivityReason: null,
      coverageLevelReason: null,
      comprehensibilityReason: null,
      precisionReason: null,
      tonalityReason: null,
      comparabilityToGoogleAiReason: null,
      sourceMatchingReason: null,
      sourceQualityReason: null,
      goalAchievementReason: null,
      dialogueSkillsReason: null,
      handlingCorrectionsReason: null,
      goodToRecommendReason: null,
    };
  }
}
