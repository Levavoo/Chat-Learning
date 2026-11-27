import { ComponentFixture, TestBed } from '@angular/core/testing';

import { RenateIconComponent } from './renate-icon.component';

describe('RenateIconComponent', () => {
  let component: RenateIconComponent;
  let fixture: ComponentFixture<RenateIconComponent>;

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [RenateIconComponent],
    }).compileComponents();

    fixture = TestBed.createComponent(RenateIconComponent);
    component = fixture.componentInstance;
    fixture.detectChanges();
  });

  it('should create', () => {
    expect(component).toBeTruthy();
  });
});
