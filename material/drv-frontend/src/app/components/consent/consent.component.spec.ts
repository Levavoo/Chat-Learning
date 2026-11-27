import { ComponentFixture, TestBed } from '@angular/core/testing';

import { ConsentComponent } from './consent.component';

describe('ConsentComponent', () => {
  let component: ConsentComponent;
  let fixture: ComponentFixture<ConsentComponent>;

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [ConsentComponent],
    }).compileComponents();

    fixture = TestBed.createComponent(ConsentComponent);
    component = fixture.componentInstance;
    fixture.detectChanges();
  });

  it('should create', () => {
    expect(component).toBeTruthy();
  });

  describe('goToChat', () => {
    it('should close the window', () => {
      const closeSpy = spyOn(window, 'close');
      component.goToChat();
      expect(closeSpy).toHaveBeenCalled();
    });
  });

  describe('onGoBackEnter', () => {
    it('should prevent default and call goToChat', () => {
      const event = jasmine.createSpyObj<Event>('Event', ['preventDefault']);
      const goToChatSpy = spyOn(component, 'goToChat');
      component.onGoBackEnter(event);
      expect(event.preventDefault).toHaveBeenCalled();
      expect(goToChatSpy).toHaveBeenCalled();
    });
    it('should call goToChat when event is undefined', () => {
      const goToChatSpy = spyOn(component, 'goToChat');
      component.onGoBackEnter(undefined as unknown as Event);
      expect(goToChatSpy).toHaveBeenCalled();
    });
  });
});
