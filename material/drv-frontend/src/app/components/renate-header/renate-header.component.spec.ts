import { ComponentFixture, TestBed } from '@angular/core/testing';
import { of } from 'rxjs';

import { AuthService } from '@auth/auth.service';
import { RenateHeaderComponent } from './renate-header.component';

describe('RenateHeaderComponent', () => {
  let component: RenateHeaderComponent;
  let fixture: ComponentFixture<RenateHeaderComponent>;

  const authServiceMock = {
    isAuthenticated$: of(false),
    logout: jasmine.createSpy('logout'),
  };

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [RenateHeaderComponent],
      providers: [{ provide: AuthService, useValue: authServiceMock }],
    }).compileComponents();

    fixture = TestBed.createComponent(RenateHeaderComponent);
    component = fixture.componentInstance;
    fixture.detectChanges();
  });

  it('should create', () => {
    expect(component).toBeTruthy();
  });

  it('should show the REVIEW pill when isReview is true', () => {
    component.isReview = true;
    fixture.detectChanges();
    const pill = fixture.nativeElement.querySelector('.review-pill');
    expect(pill).toBeTruthy();
    expect(pill.textContent).toContain('REVIEW');
  });

  it('should not show the REVIEW pill when isReview is false', () => {
    component.isReview = false;
    fixture.detectChanges();
    const pill = fixture.nativeElement.querySelector('.review-pill');
    expect(pill).toBeNull();
  });
});
