import { ComponentFixture, TestBed } from '@angular/core/testing';

import { RenateSidePanelComponent } from './renate-side-panel.component';

describe('RenateSidePanelComponent', () => {
  let component: RenateSidePanelComponent;
  let fixture: ComponentFixture<RenateSidePanelComponent>;

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [RenateSidePanelComponent],
    }).compileComponents();

    fixture = TestBed.createComponent(RenateSidePanelComponent);
    component = fixture.componentInstance;
    fixture.detectChanges();
  });

  it('should create', () => {
    expect(component).toBeTruthy();
  });
});
