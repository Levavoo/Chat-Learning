import { ComponentFixture, TestBed } from '@angular/core/testing';
import { DomSanitizer } from '@angular/platform-browser';
import { MessageChunk } from '@models/bedrock-chat.models';
import { MatomoService } from '@services/matomo/matomo.service';
import { RelatedDocumentsPanelComponent } from './related-documents-panel.component';

describe('RelatedDocumentsPanelComponent', () => {
  let component: RelatedDocumentsPanelComponent;
  let fixture: ComponentFixture<RelatedDocumentsPanelComponent>;

  let sanitizerSpy: jasmine.SpyObj<DomSanitizer>;
  let matomoServiceMock: jasmine.SpyObj<MatomoService>;

  beforeEach(async () => {
    sanitizerSpy = jasmine.createSpyObj('DomSanitizer', [
      'sanitize',
      'bypassSecurityTrustHtml',
    ]);
    matomoServiceMock = jasmine.createSpyObj('MatomoService', ['trackEvent']);

    sanitizerSpy.sanitize.and.returnValue('SANITIZED');

    await TestBed.configureTestingModule({
      imports: [RelatedDocumentsPanelComponent],
      providers: [
        { provide: DomSanitizer, useValue: sanitizerSpy },
        { provide: MatomoService, useValue: matomoServiceMock },
      ],
    }).compileComponents();

    fixture = TestBed.createComponent(RelatedDocumentsPanelComponent);
    component = fixture.componentInstance;
  });

  it('should be created', () => {
    expect(component).toBeTruthy();
  });

  describe('ngOnChanges', () => {
    it('should parse markdown and sanitize HTML when currentDocument has content', async () => {
      component.currentDocument = {
        content: '# Test Header\n\nTest content',
        sourceName: 'Test Source',
        contentType: 'text',
        rank: 1,
        title: null,
      } as MessageChunk;

      await component.ngOnChanges();

      expect(sanitizerSpy.sanitize).toHaveBeenCalled();
      expect(component.introText).toBe('SANITIZED');
    });

    it('should handle empty content', async () => {
      component.currentDocument = {
        content: '',
        sourceName: 'Test Source',
        contentType: 'text',
        rank: 1,
        title: null,
      } as MessageChunk;

      await component.ngOnChanges();

      expect(sanitizerSpy.sanitize).toHaveBeenCalled();
      expect(component.introText).toBe('SANITIZED');
    });

    it('should handle missing currentDocument', async () => {
      component.currentDocument = undefined as unknown as MessageChunk;

      await component.ngOnChanges();

      expect(sanitizerSpy.sanitize).toHaveBeenCalled();
      expect(component.introText).toBe('SANITIZED');
    });

    it('should handle sanitizer returning null', async () => {
      sanitizerSpy.sanitize.and.returnValue(null);
      component.currentDocument = {
        content: '# Test',
        sourceName: 'Test',
        contentType: 'text',
        rank: 1,
        title: null,
      } as MessageChunk;

      await component.ngOnChanges();

      expect(component.introText).toBe('');
    });
  });

  // Real-sanitizer path: marked -> SecurityContext.HTML -> [innerHTML] must preserve table markup.
  describe('table rendering with the real DomSanitizer', () => {
    let realComponent: RelatedDocumentsPanelComponent;

    beforeEach(async () => {
      TestBed.resetTestingModule();
      await TestBed.configureTestingModule({
        imports: [RelatedDocumentsPanelComponent],
      }).compileComponents();

      realComponent = TestBed.createComponent(
        RelatedDocumentsPanelComponent,
      ).componentInstance;
    });

    it('should render a GFM table as a table, not as a paragraph and <hr>', async () => {
      realComponent.currentDocument = {
        content: [
          '| Beginn der Rente wegen Erwerbsminderung Jahr | frühestmöglicher Rentenbeginn ohne Abschläge ab Jahre | frühestmöglicher Rentenbeginn ohne Abschläge ab Monate | vorzeitiger Rentenbeginn mit Höchstabschlag bis Jahre | vorzeitiger Rentenbeginn mit Höchstabschlag bis Monate |',
          '| --- | --- | --- | --- | --- |',
          '| 2019 | 64 | 2 | 61 | 2 |',
          '| 2024 | 65 | 0 | 62 | 0 |',
        ].join('\n'),
      } as MessageChunk;

      await realComponent.ngOnChanges();
      const html = String(realComponent.introText);

      expect(html).toContain('<table>');
      expect((html.match(/<th>/g) ?? []).length).toBe(5);
      expect(html).toContain('<td>2024</td>');
      expect(html).not.toContain('<hr>');
      expect(html).not.toContain('|');
    });

    it('should keep an important note heading and body inside one grey-box blockquote', async () => {
      const body =
        'Bitte informieren Sie sich rechtzeitig, wenn Sie die Aufnahme einer Beschäftigung oder Tätigkeit beabsichtigen oder wenn sich eine bestehende Erwerbstätigkeit ändert.';
      realComponent.currentDocument = {
        content: `**Bitte beachten Sie::**\n\n${body}`,
      } as MessageChunk;

      await realComponent.ngOnChanges();
      const html = String(realComponent.introText);
      const rendered = document.createElement('div');
      rendered.innerHTML = html;
      const blockquote = rendered.querySelector('blockquote');

      expect(html).not.toContain(':**');
      expect(blockquote).not.toBeNull();
      expect(blockquote?.querySelector('h5')?.textContent).toBe(
        'Bitte beachten Sie:',
      );
      expect(blockquote?.querySelector('p')?.textContent).toBe(body);
    });
  });

  describe('goToBrochure', () => {
    it('should open URL in new window', () => {
      const windowOpenSpy = spyOn(window, 'open');
      const testUrl = 'https://example.com/brochure.pdf';

      component.goToBrochure(testUrl);

      expect(windowOpenSpy).toHaveBeenCalledWith(
        testUrl,
        '_blank',
        'noopener, noreferrer ',
      );
    });

    it('should track Broschüre-Link with brochureNumber when present (B2)', () => {
      spyOn(window, 'open');
      component.currentDocument = { brochureNumber: 'A220' } as MessageChunk;

      component.goToBrochure('https://example.com/brochure.pdf');

      expect(matomoServiceMock.trackEvent).toHaveBeenCalledWith(
        'Chatbot',
        'Broschüre-Link',
        'A220',
      );
    });

    it('should track Broschüre-Link with URL when brochureNumber is null (B2)', () => {
      spyOn(window, 'open');
      component.currentDocument = {
        brochureNumber: undefined,
      } as unknown as MessageChunk;

      component.goToBrochure('https://example.com/fallback.pdf');

      expect(matomoServiceMock.trackEvent).toHaveBeenCalledWith(
        'Chatbot',
        'Broschüre-Link',
        'https://example.com/fallback.pdf',
      );
    });
  });

  describe('normalizeHintLabels', () => {
    it('should normalize labels', async () => {
      component.currentDocument = {
        content: '**Unser Tipp:**\n\nUnser Tipp:\n\nWir wollen Sie',
        sourceName: 'Test',
        contentType: 'text',
        rank: 1,
        title: null,
      } as MessageChunk;

      const result = component.normalizeHintLabels(
        component.currentDocument.content,
      );
      const expectedValue = `> ##### Unser Tipp:
Wir wollen Sie`;
      expect(result).toBe(expectedValue);
    });

    it('should repair already-indexed labels with a duplicated colon', () => {
      const body =
        'Bitte informieren Sie sich rechtzeitig, wenn Sie die Aufnahme einer Beschäftigung oder Tätigkeit beabsichtigen oder wenn sich eine bestehende Erwerbstätigkeit ändert.';

      const result = component.normalizeHintLabels(
        `**Bitte beachten Sie::**\n\n${body}`,
      );

      expect(result).toBe(`> ##### Bitte beachten Sie:\n${body}`);
    });

    it('should handle empty input safely', () => {
      const output = component.normalizeHintLabels('');
      expect(output).toBe('');
    });
  });

  describe('getBrochureButtonLabel', () => {
    it('should return FAQ label for FAQ sources', () => {
      component.currentDocument = {
        brochureNumber: 'faq-a-und-b',
      } as MessageChunk;
      expect(component.getBrochureButtonLabel()).toBe('Zu allen FAQs');
    });

    it('should return Broschüre label for brochure sources', () => {
      component.currentDocument = { brochureNumber: 'B03' } as MessageChunk;
      expect(component.getBrochureButtonLabel()).toBe('Zur gesamten Broschüre');
    });

    it('should return Broschüre label for merkblatt sources', () => {
      component.currentDocument = {
        brochureNumber: 'G0103',
        category: 'Merkblatt',
      } as MessageChunk;
      expect(component.getBrochureButtonLabel()).toBe('Zum gesamten Merkblatt');
    });
  });
});
