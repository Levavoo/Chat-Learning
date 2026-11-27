import { PrintPreviewComponent } from './print-preview.component';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { BedrockChatService } from '@services/bedrock-chat/bedrock-chat.service';

describe('PrintPreviewComponent', () => {
  let component: PrintPreviewComponent;
  let fixture: ComponentFixture<PrintPreviewComponent>;

  beforeEach(() => {
    TestBed.configureTestingModule({
      providers: [
        {
          provide: BedrockChatService,
          useValue: { chatMessages: [] },
        },
      ],
    }).overrideComponent(PrintPreviewComponent, {
      set: { template: '<div class="print-disclaimer"></div>' },
    });

    fixture = TestBed.createComponent(PrintPreviewComponent);
    component = fixture.componentInstance;
  });

  it('should not throw when disclaimer does not exist', () => {
    expect(() => component.ngAfterViewInit()).not.toThrow();
  });
});
