import { ComponentFixture, TestBed } from '@angular/core/testing';

import { provideHttpClient } from '@angular/common/http';
import { provideHttpClientTesting } from '@angular/common/http/testing';
import { FeedbackService } from '@services/feedback/feedback.service';
import { FeedbackComponent } from './feedback.component';
import { ReactiveFormsModule } from '@angular/forms';
import { MessageFeedback } from '@models/bedrock-chat.models';
import { ENV_CONFIG } from 'src/app/environment.token';

describe('FeedbackComponent', () => {
  let component: FeedbackComponent;
  let fixture: ComponentFixture<FeedbackComponent>;

  let feedbackServiceMock: jasmine.SpyObj<FeedbackService>;

  beforeEach(async () => {
    feedbackServiceMock = jasmine.createSpyObj('FeedbackService', [
      'saveFeedback',
      'createFeedbackRating',
      'getLastAssistantMessageId',
    ]);

    await TestBed.configureTestingModule({
      imports: [FeedbackComponent, ReactiveFormsModule],
      providers: [
        {
          provide: ENV_CONFIG,
          useValue: {
            apiEndpoint: '',
            userPoolId: '',
            userPoolClientId: '',
            region: '',
            redirectSigninUrl: '',
            redirectSignoutUrl: '',
            cognitoDomain: '',
            anonymousAccess: false,
            intern: true,
          },
        },
        { provide: FeedbackService, useValue: feedbackServiceMock },
        provideHttpClient(),
        provideHttpClientTesting(),
      ],
    }).compileComponents();

    localStorage.removeItem('isMultiturn');
    localStorage.removeItem('usedScenario');
    fixture = TestBed.createComponent(FeedbackComponent);
    component = fixture.componentInstance;
    fixture.detectChanges();
  });

  afterEach(() => {
    localStorage.removeItem('isMultiturn');
    localStorage.removeItem('usedScenario');
  });

  it('should create', () => {
    expect(component).toBeTruthy();
  });

  it('should initialize form on ngOnInit', () => {
    component.ngOnInit();
    expect(component.form).toBeDefined();
    expect(component.form.get('testingType')).toBeTruthy();
    expect(component.form.invalid).toBeTrue();
  });

  it('should display restored multiturn selections as text', () => {
    localStorage.setItem('isMultiturn', 'true');
    localStorage.setItem('usedScenario', '1');
    fixture.destroy();

    fixture = TestBed.createComponent(FeedbackComponent);
    component = fixture.componentInstance;
    component.feedbackPerTurn = { type: 'conversation' };
    const updateTestingTypeSpy = spyOn(
      component,
      'updateTestingTypeValue',
    ).and.callThrough();
    fixture.detectChanges();

    expect(updateTestingTypeSpy).toHaveBeenCalledWith('multiturn');
    expect(component.rawFeedbackRating.isMultiturn).toBeTrue();
    expect(component.form.getRawValue().testingType).toEqual(['multiturn']);
    expect(component.form.getRawValue().usedScenario).toEqual([1]);

    const content = fixture.nativeElement.textContent;
    expect(content).toContain('Testart: Dialogtest (Multi-Turn)');
    expect(content).toContain('Ihr Szenario: 1');
    expect(
      fixture.nativeElement.querySelector('[name="Multiturn"]'),
    ).toBeNull();
    expect(
      fixture.nativeElement.querySelector('[name="usedScenario"]'),
    ).toBeNull();
  });

  describe('updateTestingTypeValue', () => {
    it('should set singleturn form and flags', () => {
      component.updateTestingTypeValue('singleturn');

      expect(component.rawFeedbackRating.isSingleturn).toBeTrue();
      expect(component.rawFeedbackRating.isMultiturn).toBeFalse();
      expect(component.rawFeedbackRating.isFreeUserTest).toBeFalse();
      expect(component.rawFeedbackRating.isFinalFeedback).toBeFalse();

      expect(component.form.get('technicalCorrectivity')).toBeTruthy();
      expect(component.form.get('coverageLevel')).toBeTruthy();
      expect(component.form.get('comment')).toBeTruthy();
    });

    it('should set final feedback form and flags', () => {
      component.updateTestingTypeValue('finalFeedback');

      expect(component.rawFeedbackRating.isSingleturn).toBeFalse();
      expect(component.rawFeedbackRating.isMultiturn).toBeFalse();
      expect(component.rawFeedbackRating.isFreeUserTest).toBeFalse();
      expect(component.rawFeedbackRating.isFinalFeedback).toBeTrue();

      expect(component.form.get('goodToRecommend')).toBeTruthy();
    });

    it('should set producer and scope of each form', () => {
      const pairs = (): Pick<MessageFeedback, 'producer' | 'scope'> => {
        const { producer, scope } = component.form.getRawValue();
        return { producer, scope };
      };

      component.updateTestingTypeValue('singleturn');
      expect(pairs()).toEqual({
        producer: 'internal_single_turn',
        scope: 'message',
      });

      component.updateTestingTypeValue('multiturn');
      expect(pairs()).toEqual({
        producer: 'internal_multi_turn',
        scope: 'dialog',
      });

      component.updateTestingTypeValue('finalFeedback');
      expect(pairs()).toEqual({
        producer: 'internal_final_feedback',
        scope: 'test',
      });

      component.feedbackPerTurn = { type: 'perTurn' };
      component.ngOnInit();
      expect(pairs()).toEqual({
        producer: 'internal_multi_turn',
        scope: 'turn',
      });
    });
  });

  describe('onFeedbackEnter', () => {
    it('should prevent default and save feedback on enter', () => {
      const event = jasmine.createSpyObj('event', ['preventDefault']);
      spyOn(component, 'doSaveFeedback');

      component.onFeedbackEnter(event as Event);

      expect(event.preventDefault).toHaveBeenCalled();
      expect(component.doSaveFeedback).toHaveBeenCalled();
    });
  });

  describe('isRatingNotSetOrSubmitting', () => {
    it('should return true when form is invalid', () => {
      component.ngOnInit();
      expect(component.isRatingNotSetOrSubmitting()).toBeTrue();
    });

    it('should return false when form is valid', () => {
      component.updateTestingTypeValue('freeUser');
      component.form.patchValue({
        testingType: 'freeUser',
        utilityValue: '5',
      });

      expect(component.isRatingNotSetOrSubmitting()).toBeFalse();
    });
  });

  it('should create feedback rating and emit it', () => {
    const mockRating = {
      isMultiturn: false,
      isSingleturn: false,
      isFreeUserTest: false,
      isFinalFeedback: true,
      goodToRecommend: 'Yes',
    } as MessageFeedback;
    feedbackServiceMock.createFeedbackRating.and.returnValue(mockRating);
    spyOn(component.feedbackSaved, 'emit');

    component.updateTestingTypeValue('freeUser');
    component.form.patchValue({
      testingType: 'freeUser',
      utilityValue: '5',
    });

    component.doSaveFeedback();

    expect(feedbackServiceMock.createFeedbackRating).toHaveBeenCalled();
    expect(component.feedbackSaved.emit).toHaveBeenCalledWith(mockRating);
  });
});
