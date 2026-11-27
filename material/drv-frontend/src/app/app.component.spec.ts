import { ComponentFixture, TestBed } from '@angular/core/testing';
import { BedrockChatService } from '@services/bedrock-chat/bedrock-chat.service';
import {} from 'jasmine';
import { AppComponent } from './app.component';

describe('AppComponent', () => {
  let component: AppComponent;
  let fixture: ComponentFixture<AppComponent>;
  let localStorageMock: Record<string, string>;
  let classListMock: string[];

  const bedrockChatServiceMock = {
    initChat() {
      return;
    },
  };

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [AppComponent],
      providers: [
        { provide: BedrockChatService, useValue: bedrockChatServiceMock },
      ],
    }).compileComponents();
  });

  beforeEach(() => {
    fixture = TestBed.createComponent(AppComponent);
    component = fixture.componentInstance;
    fixture.detectChanges();
    localStorageMock = {};
    classListMock = [];

    spyOn(window.localStorage, 'getItem').and.callFake((theme) =>
      theme in localStorageMock ? localStorageMock[theme] : null,
    );
    spyOn(window.localStorage, 'setItem').and.callFake(
      (key, value) => (localStorageMock[key] = value + ''),
    );
  });

  it('should create', () => {
    expect(component).toBeTruthy();
  });

  describe('ngOnInit', () => {
    beforeEach(() => {
      spyOn(document.body.classList, 'add').and.callFake((classElement) =>
        classListMock.push(classElement),
      );
      spyOn(document.body.classList, 'remove').and.callFake(
        (classElement) =>
          (classListMock = classListMock.filter((obj) => obj !== classElement)),
      );
    });

    it('should contain light theme in localStorage after init, if theme is not set before', () => {
      component.ngOnInit();
      expect(localStorageMock['theme']).toBe('light');
    });

    it('should contain light theme in localStorage after init, if theme was set light before', () => {
      localStorageMock['theme'] = 'light';
      component.ngOnInit();
      expect(localStorageMock['theme']).toBe('light');
    });

    it('should contain dark theme in localStorage after init, if theme was set dark before', () => {
      localStorageMock['theme'] = 'dark';
      component.ngOnInit();
      expect(localStorageMock['theme']).toBe('dark');
    });

    it('should remove dark-theme from classList when localStorage theme is set to light', () => {
      classListMock.push('drv-theme--dark');
      localStorageMock['theme'] = 'light';
      component.ngOnInit();
      expect(classListMock).not.toContain('drv-theme--dark');
    });

    it('should add dark-theme to classList when localStorage theme is set to dark', () => {
      classListMock = classListMock.filter((obj) => obj !== 'drv-theme--dark');
      localStorageMock['theme'] = 'dark';
      component.ngOnInit();
      expect(classListMock).toContain('drv-theme--dark');
    });
  });

  describe('ngAfterViewInit', () => {
    it('should do nothing if dark mode toggle is missing', () => {
      spyOn(document, 'querySelector').and.returnValue(null);

      expect(() => component.ngAfterViewInit()).not.toThrow();
    });

    it('should do nothing if toggle text is missing', () => {
      const toggle = document.createElement('div');
      toggle.classList.add('drv-dark-mode-toggle');

      spyOn(document, 'querySelector').and.returnValue(toggle);

      expect(() => component.ngAfterViewInit()).not.toThrow();
    });
  });
});
