import {
  Component,
  EventEmitter,
  inject,
  Input,
  OnChanges,
  OnInit,
  Output,
  SimpleChanges,
} from '@angular/core';
import {
  FormBuilder,
  FormGroup,
  FormsModule,
  ReactiveFormsModule,
  Validators,
} from '@angular/forms';
import {
  ButtonbarComponent,
  ButtonComponent,
  InputGroupComponent,
  Notification,
  NotificationService,
  RadiobuttonComponent,
  TextareaComponent,
} from '@drv-ds/drv-design-system-ng';
import { MessageFeedback } from '@models/bedrock-chat.models';
import { FEEDBACK_RATING_VALUES } from '@models/feedback/feedback-internal-constants';
import {
  feedbackModalId,
  FeedbackType,
  rating,
  RawFeedbackRating,
} from '@models/feedback/feedback.model';
import { FeedbackService } from '@services/feedback/feedback.service';
import { ENV_CONFIG } from 'src/app/environment.token';

export interface LocalNotification extends Notification {
  notificationId?: string;
}

function createEmptyRawFeedbackRating(): RawFeedbackRating {
  return {
    isMultiturn: false,
    isSingleturn: false,
    isFreeUserTest: false,
    isFinalFeedback: false,
    isPerTurnFeedback: false,
    technicalCorrectivity: [],
    coverageLevel: [],
    comprehensibility: [],
    tonality: [],
    utilityValue: [],
    comparabilityToGoogleAi: [],
    sourceMatching: [],
    sourceQuality: [],
    usedScenario: undefined,
    goalAchievement: [],
    dialogueSkills: [],
    furtherDevelopment: [],
    comment: '',
  };
}

@Component({
  selector: 'drv-feedback',
  standalone: true,
  imports: [
    FormsModule,
    ButtonComponent,
    ButtonbarComponent,
    TextareaComponent,
    RadiobuttonComponent,
    InputGroupComponent,
    ReactiveFormsModule,
  ],
  providers: [NotificationService],
  templateUrl: './feedback.component.html',
  styleUrl: './feedback.component.scss',
})
export class FeedbackComponent implements OnInit, OnChanges {
  @Input() feedbackPerTurn: FeedbackType = {};

  @Output()
  submitted = new EventEmitter<boolean>();

  @Output()
  // eslint-disable-next-line @angular-eslint/no-output-on-prefix
  onSubmit = new EventEmitter<boolean>();

  @Output()
  // eslint-disable-next-line @angular-eslint/no-output-on-prefix
  onNotificationSending = new EventEmitter<LocalNotification>();

  @Output()
  // eslint-disable-next-line @angular-eslint/no-output-on-prefix
  onDoSaveFeedback = new EventEmitter<MessageFeedback>();

  @Output()
  feedbackSaved = new EventEmitter<MessageFeedback>();

  form: FormGroup = new FormGroup({});
  public feedbackModalId: string = feedbackModalId;
  public feedbackErrorModalId = `${this.feedbackModalId}_error`;
  private readonly env = inject(ENV_CONFIG);

  isInternal: boolean = this.env.intern;
  isMultiturnSelected = localStorage.getItem('isMultiturn') === 'true';
  usedScenario: string | null | undefined = this.isMultiturnSelected
    ? localStorage.getItem('usedScenario')
    : undefined;
  rating = rating;

  rawFeedbackRating: RawFeedbackRating = createEmptyRawFeedbackRating();

  private fb = inject(FormBuilder);
  private readonly feedbackService: FeedbackService = inject(FeedbackService);
  FEEDBACK_RATING_VALUES = FEEDBACK_RATING_VALUES;

  ngOnInit(): void {
    this.initializeFormForFeedbackType();
  }

  ngOnChanges(changes: SimpleChanges): void {
    const feedbackPerTurnChange = changes['feedbackPerTurn'];
    if (
      feedbackPerTurnChange &&
      !feedbackPerTurnChange.firstChange &&
      (feedbackPerTurnChange.previousValue?.type !==
        feedbackPerTurnChange.currentValue?.type ||
        feedbackPerTurnChange.previousValue?.value !==
          feedbackPerTurnChange.currentValue?.value)
    ) {
      this.rawFeedbackRating = createEmptyRawFeedbackRating();
      this.initializeFormForFeedbackType();
    }
  }

  private initializeFormForFeedbackType(): void {
    this.form = this.fb.group({ testingType: [[], [Validators.required]] });
    if (this.feedbackPerTurn?.type === 'perTurn') {
      this.rawFeedbackRating.isSingleturn = false;
      this.rawFeedbackRating.isMultiturn = true;
      this.rawFeedbackRating.isFreeUserTest = false;
      this.rawFeedbackRating.isFinalFeedback = false;
      this.rawFeedbackRating.isPerTurnFeedback = true;
      this.form = this.fb.group({
        testingType: [['multiturn'], [Validators.required]],
        isMultiturn: true,
        isPerTurnFeedback: true,
        producer: 'internal_multi_turn',
        scope: 'turn',
        usedScenario: [
          this.usedScenario ? [+this.usedScenario] : '',
          Validators.required,
        ],
        technicalCorrectivity: ['', [Validators.required]],
        comment: '',
      });
    } else if (
      this.feedbackPerTurn?.type === 'conversation' &&
      this.isMultiturnSelected &&
      this.usedScenario
    ) {
      this.updateTestingTypeValue('multiturn');
    }
  }

  updateTestingTypeValue(value: string | number): void {
    const testingType = String(value);
    switch (testingType) {
      case 'singleturn':
        this.rawFeedbackRating.isSingleturn = true;
        this.rawFeedbackRating.isMultiturn = false;
        this.rawFeedbackRating.isFreeUserTest = false;
        this.rawFeedbackRating.isFinalFeedback = false;
        this.rawFeedbackRating.isPerTurnFeedback = false;
        localStorage.setItem('isMultiturn', 'false');
        this.form = this.fb.group({
          testingType: [[testingType], [Validators.required]],
          isSingleturn: true,
          producer: 'internal_single_turn',
          scope: 'message',
          technicalCorrectivity: ['', [Validators.required]],
          coverageLevel: ['', [Validators.required]],
          tonality: ['', [Validators.required]],
          comprehensibility: ['', [Validators.required]],
          precision: ['', [Validators.required]],
          sourceMatching: ['', [Validators.required]],
          sourceQuality: ['', [Validators.required]],
          comparabilityToGoogleAi: ['', [Validators.required]],
          comment: '',
        });
        break;
      case 'multiturn':
        this.rawFeedbackRating.isSingleturn = false;
        this.rawFeedbackRating.isMultiturn = true;
        this.rawFeedbackRating.isFreeUserTest = false;
        this.rawFeedbackRating.isFinalFeedback = false;
        this.rawFeedbackRating.isPerTurnFeedback = false;
        if (localStorage.getItem('isMultiturn') === '') {
          localStorage.setItem('isMultiturn', 'true');
        }
        this.form = this.fb.group({
          testingType: [
            {
              value: [testingType],
              disabled: this.isMultiturnSelected,
            },
            [Validators.required],
          ],
          isMultiturn: true,
          isPerTurnFeedback: false,
          producer: 'internal_multi_turn',
          scope: 'dialog',
          usedScenario: [
            this.usedScenario ? [+this.usedScenario] : '',
            [Validators.required],
          ],
          dialogueSkills: ['', [Validators.required]],
          goalAchievement: ['', [Validators.required]],
          handlingCorrections: ['', []],
          comment: '',
        });
        break;
      case 'finalFeedback':
        this.rawFeedbackRating.isSingleturn = false;
        this.rawFeedbackRating.isMultiturn = false;
        this.rawFeedbackRating.isFreeUserTest = false;
        this.rawFeedbackRating.isFinalFeedback = true;
        this.rawFeedbackRating.isPerTurnFeedback = false;
        localStorage.setItem('isMultiturn', 'false');
        this.form = this.fb.group({
          testingType: [[testingType], [Validators.required]],
          isFinalFeedback: true,
          producer: 'internal_final_feedback',
          scope: 'test',
          goodToRecommend: ['', [Validators.required]],
          comment: '',
        });
    }
  }

  updateUsedScenario(value: (string | number)[]): void {
    this.usedScenario = value?.toString() ?? null;
  }

  getScenarioTitle(scenarioValue: string | null | undefined): string {
    if (!scenarioValue) return '';
    const option = FEEDBACK_RATING_VALUES.multiturn.usedScenario.options.find(
      (opt) => String(opt.value) === scenarioValue,
    );
    return option?.title ?? '';
  }

  onFeedbackEnter(event: Event) {
    event?.preventDefault();
    this.doSaveFeedback();
  }

  isRatingNotSetOrSubmitting(): boolean {
    return this.form.invalid;
  }

  doSaveFeedback() {
    const formValue = this.form.getRawValue() as RawFeedbackRating;
    const rating = this.feedbackService.createFeedbackRating(formValue);
    if (formValue.isMultiturn === true) {
      localStorage.setItem('isMultiturn', 'true');
      localStorage.setItem('usedScenario', this.usedScenario ?? '');
    }
    this.feedbackSaved.emit(rating);
  }
}
