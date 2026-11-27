import { Component, computed, inject, OnInit, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import {
  ButtonComponent,
  ColDirective,
  GridDirective,
  NotificationComponent,
  NotificationService,
  RowDirective,
  TextinputComponent,
} from '@drv-ds/drv-design-system-ng';
import {
  AnalyticsResponse,
  AnalyticsService,
  DocumentInventoryItem,
  DocumentInventoryResponse,
} from '@services/analytics/analytics.service';

@Component({
  standalone: true,
  selector: 'drv-dashboard-page',
  imports: [
    FormsModule,
    ButtonComponent,
    ColDirective,
    GridDirective,
    NotificationComponent,
    RowDirective,
    TextinputComponent,
  ],
  providers: [NotificationService],
  templateUrl: './dashboard-page.component.html',
  styleUrl: './dashboard-page.component.scss',
})
export class DashboardPageComponent implements OnInit {
  private readonly analyticsService = inject(AnalyticsService);
  private readonly notificationService = inject(NotificationService);

  data = signal<AnalyticsResponse | null>(null);
  loading = signal(true);
  documents = signal<DocumentInventoryResponse | null>(null);
  documentsLoading = signal(false);
  categoryFilter = signal<string>('');
  documentsExpanded = signal(false);

  readonly minFromDate = this.toDateInput(
    Date.now() - 180 * 24 * 60 * 60 * 1000,
  );
  fromDate = this.toDateInput(Date.now() - 30 * 24 * 60 * 60 * 1000);
  toDate = this.toDateInput(Date.now());

  readonly availableCategories = computed<string[]>(() => {
    const docs = this.documents()?.documents ?? [];
    const cats = [
      ...new Set(docs.map((d) => d.category ?? '').filter(Boolean)),
    ];
    return cats.sort();
  });

  readonly filteredDocuments = computed<DocumentInventoryItem[]>(() => {
    const docs = this.documents()?.documents ?? [];
    const cat = this.categoryFilter();
    return cat ? docs.filter((d) => d.category === cat) : docs;
  });

  ngOnInit() {
    this.load();
    this.loadDocuments();
  }

  load() {
    const minMs = Date.now() - 180 * 24 * 60 * 60 * 1000;
    if (new Date(this.fromDate).getTime() < minMs) {
      this.fromDate = this.minFromDate;
    }
    this.loading.set(true);
    this.analyticsService
      .getAnalytics(
        new Date(this.fromDate).getTime(),
        new Date(this.toDate).getTime() + 86_400_000,
      )
      .subscribe({
        next: (d) => {
          this.data.set(d);
          this.loading.set(false);
        },
        error: () => {
          this.loading.set(false);
          this.notificationService.update({
            variant: 'alert',
            title: 'Fehler beim Laden der Daten',
            text: 'Bitte versuche es erneut.',
          });
        },
      });
  }

  loadDocuments() {
    this.documentsLoading.set(true);
    this.analyticsService.getDocuments().subscribe({
      next: (d) => {
        this.documents.set(d);
        this.documentsLoading.set(false);
      },
      error: () => {
        this.documentsLoading.set(false);
      },
    });
  }

  toggleDocuments() {
    this.documentsExpanded.update((v) => !v);
  }

  get maxDomainCount(): number {
    return Math.max(1, ...(this.data()?.topDomains.map((d) => d.count) ?? []));
  }

  get maxSourceCount(): number {
    return Math.max(1, ...(this.data()?.topSources.map((s) => s.count) ?? []));
  }

  get thumbsUpPercent(): string {
    const rate = this.data()?.feedbackThumbsUpRate;
    return rate != null ? `${Math.round(rate * 100)} %` : '–';
  }

  get feedbackGoodPercent(): string {
    const d = this.data();
    if (!d) return '–';
    const total =
      d.feedbackGoodCount + d.feedbackNeutralCount + d.feedbackBadCount;
    if (total === 0) return '–';
    return `${Math.round((d.feedbackGoodCount / total) * 100)} %`;
  }

  get feedbackNeutralPercent(): string {
    const d = this.data();
    if (!d) return '–';
    const total =
      d.feedbackGoodCount + d.feedbackNeutralCount + d.feedbackBadCount;
    if (total === 0) return '–';
    return `${Math.round((d.feedbackNeutralCount / total) * 100)} %`;
  }

  get feedbackBadPercent(): string {
    const d = this.data();
    if (!d) return '–';
    const total =
      d.feedbackGoodCount + d.feedbackNeutralCount + d.feedbackBadCount;
    if (total === 0) return '–';
    return `${Math.round((d.feedbackBadCount / total) * 100)} %`;
  }

  get feedbackResponseRate(): string {
    const d = this.data();
    if (!d || d.totalMessages === 0) return '–';
    const total =
      d.feedbackGoodCount + d.feedbackNeutralCount + d.feedbackBadCount;
    return `${Math.round((total / d.totalMessages) * 100)} %`;
  }

  get blockedPercent(): string {
    const rate = this.data()?.blockedRate;
    return rate != null ? `${Math.round(rate * 100)} %` : '–';
  }

  private toDateInput(ms: number): string {
    return new Date(ms).toISOString().split('T')[0];
  }
}
