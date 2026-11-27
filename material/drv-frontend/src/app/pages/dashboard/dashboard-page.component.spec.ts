import { ComponentFixture, TestBed } from '@angular/core/testing';
import { provideHttpClient } from '@angular/common/http';
import { provideHttpClientTesting } from '@angular/common/http/testing';
import { FormsModule } from '@angular/forms';
import { of, throwError } from 'rxjs';
import { DashboardPageComponent } from './dashboard-page.component';
import {
  AnalyticsResponse,
  AnalyticsService,
  DocumentInventoryResponse,
} from '@services/analytics/analytics.service';
import { NotificationService } from '@drv-ds/drv-design-system-ng';

describe('DashboardPageComponent', () => {
  let component: DashboardPageComponent;
  let fixture: ComponentFixture<DashboardPageComponent>;
  let analyticsServiceMock: jasmine.SpyObj<AnalyticsService>;
  let notificationServiceMock: jasmine.SpyObj<NotificationService>;

  const mockResponse: AnalyticsResponse = {
    totalSessions: 42,
    totalMessages: 210,
    avgMessagesPerSession: 5,
    topDomains: [
      { domain: 'rente', count: 100 },
      { domain: 'reha', count: 30 },
    ],
    topSources: [
      { sourceName: 'Broschüre A', count: 50 },
      { sourceName: 'Merkblatt B', count: 20 },
    ],
    feedbackThumbsUpRate: 0.85,
    blockedRate: 0.03,
    feedbackGoodCount: 40,
    feedbackNeutralCount: 20,
    feedbackBadCount: 10,
    topTopics: [
      { topic: 'altersrente_regulaer', domain: 'rente', count: 42 },
      { topic: 'reha_medizinisch', domain: 'reha', count: 18 },
    ],
    topicTimeSeries: [
      {
        topic: 'altersrente_regulaer',
        dataPoints: [
          { weekStart: '2026-06-02', count: 20 },
          { weekStart: '2026-06-09', count: 22 },
        ],
      },
    ],
  };

  const mockDocuments: DocumentInventoryResponse = {
    totalDocuments: 2,
    documents: [
      {
        docId: 'B01',
        title: 'Reha',
        edition: '1. Auflage',
        published: '2024',
        category: 'Rehabilitation',
        sectionCount: 10,
      },
      {
        docId: 'B02',
        title: 'Rente',
        edition: '2. Auflage',
        published: '2023',
        category: 'Rente',
        sectionCount: 5,
      },
    ],
  };

  beforeEach(async () => {
    analyticsServiceMock = jasmine.createSpyObj('AnalyticsService', [
      'getAnalytics',
      'getDocuments',
    ]);
    analyticsServiceMock.getAnalytics.and.returnValue(of(mockResponse));
    analyticsServiceMock.getDocuments.and.returnValue(of(mockDocuments));

    notificationServiceMock = jasmine.createSpyObj('NotificationService', [
      'update',
    ]);

    await TestBed.configureTestingModule({
      imports: [DashboardPageComponent, FormsModule],
      providers: [
        { provide: AnalyticsService, useValue: analyticsServiceMock },
        provideHttpClient(),
        provideHttpClientTesting(),
      ],
    })
      .overrideComponent(DashboardPageComponent, {
        set: {
          providers: [
            { provide: NotificationService, useValue: notificationServiceMock },
          ],
        },
      })
      .compileComponents();

    fixture = TestBed.createComponent(DashboardPageComponent);
    component = fixture.componentInstance;
  });

  it('should create', () => {
    expect(component).toBeTruthy();
  });

  it('should load analytics on init', () => {
    fixture.detectChanges();
    expect(analyticsServiceMock.getAnalytics).toHaveBeenCalled();
    expect(component.data()).toEqual(mockResponse);
    expect(component.loading()).toBeFalse();
  });

  it('should show error notification on API failure', () => {
    analyticsServiceMock.getAnalytics.and.returnValue(
      throwError(() => new Error('Network error')),
    );
    fixture.detectChanges();
    expect(component.loading()).toBeFalse();
    expect(component.data()).toBeNull();
    expect(notificationServiceMock.update).toHaveBeenCalledWith(
      jasmine.objectContaining({ variant: 'alert' }),
    );
  });

  it('should compute thumbsUpPercent correctly', () => {
    fixture.detectChanges();
    expect(component.thumbsUpPercent).toBe('85 %');
  });

  it('should return dash when feedbackThumbsUpRate is null', () => {
    analyticsServiceMock.getAnalytics.and.returnValue(
      of({ ...mockResponse, feedbackThumbsUpRate: null }),
    );
    fixture.detectChanges();
    expect(component.thumbsUpPercent).toBe('–');
  });

  it('should compute feedbackGoodPercent correctly', () => {
    fixture.detectChanges();
    expect(component.feedbackGoodPercent).toBe('57 %');
  });

  it('should compute feedbackNeutralPercent correctly', () => {
    fixture.detectChanges();
    expect(component.feedbackNeutralPercent).toBe('29 %');
  });

  it('should compute feedbackBadPercent correctly', () => {
    fixture.detectChanges();
    expect(component.feedbackBadPercent).toBe('14 %');
  });

  it('should compute feedbackResponseRate correctly', () => {
    fixture.detectChanges();
    expect(component.feedbackResponseRate).toBe('33 %');
  });

  it('should return dash for feedback percents when no data', () => {
    analyticsServiceMock.getAnalytics.and.returnValue(
      of(null as unknown as AnalyticsResponse),
    );
    fixture.detectChanges();
    expect(component.feedbackGoodPercent).toBe('–');
  });

  it('should compute blockedPercent correctly', () => {
    fixture.detectChanges();
    expect(component.blockedPercent).toBe('3 %');
  });

  it('should compute maxDomainCount from top domains', () => {
    fixture.detectChanges();
    expect(component.maxDomainCount).toBe(100);
  });

  it('should compute maxSourceCount from top sources', () => {
    fixture.detectChanges();
    expect(component.maxSourceCount).toBe(50);
  });

  it('should reload data when load() is called', () => {
    fixture.detectChanges();
    analyticsServiceMock.getAnalytics.calls.reset();
    component.load();
    expect(analyticsServiceMock.getAnalytics).toHaveBeenCalled();
  });

  it('should have minFromDate set to ~6 months ago', () => {
    const minMs = Date.now() - 180 * 24 * 60 * 60 * 1000;
    const minDate = new Date(minMs).toISOString().split('T')[0];
    expect(component.minFromDate).toBe(minDate);
  });

  it('should clamp fromDate to 6-month min when load() is called with an older date', () => {
    component.fromDate = '2000-01-01';
    fixture.detectChanges();
    analyticsServiceMock.getAnalytics.calls.reset();
    component.load();
    expect(component.fromDate).toBe(component.minFromDate);
  });

  it('should load documents on init', () => {
    fixture.detectChanges();
    expect(analyticsServiceMock.getDocuments).toHaveBeenCalled();
    expect(component.documents()).toEqual(mockDocuments);
    expect(component.documentsLoading()).toBeFalse();
  });

  it('should compute availableCategories from documents', () => {
    fixture.detectChanges();
    expect(component.availableCategories()).toEqual([
      'Rehabilitation',
      'Rente',
    ]);
  });

  it('should filter documents by category', () => {
    fixture.detectChanges();
    component.categoryFilter.set('Rente');
    expect(component.filteredDocuments().length).toBe(1);
    expect(component.filteredDocuments()[0].docId).toBe('B02');
  });

  it('should return all documents when no category filter is set', () => {
    fixture.detectChanges();
    expect(component.filteredDocuments().length).toBe(2);
  });

  it('should toggle documentsExpanded on toggleDocuments()', () => {
    expect(component.documentsExpanded()).toBeFalse();
    component.toggleDocuments();
    expect(component.documentsExpanded()).toBeTrue();
    component.toggleDocuments();
    expect(component.documentsExpanded()).toBeFalse();
  });

  it('should handle documents load error gracefully', () => {
    analyticsServiceMock.getDocuments.and.returnValue(
      throwError(() => new Error('S3 error')),
    );
    fixture.detectChanges();
    expect(component.documentsLoading()).toBeFalse();
    expect(component.documents()).toBeNull();
  });
});
