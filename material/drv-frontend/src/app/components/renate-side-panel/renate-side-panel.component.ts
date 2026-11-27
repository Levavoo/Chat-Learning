import {
  AfterViewInit,
  Component,
  ElementRef,
  EventEmitter,
  Output,
  ViewChild,
} from '@angular/core';
import {
  ButtonbarComponent,
  ButtonComponent,
  NotificationComponent,
} from '@drv-ds/drv-design-system-ng';
import { feedbackNotificationId } from '@models/messages/messages.models';

@Component({
  selector: 'drv-renate-side-panel',
  imports: [ButtonbarComponent, ButtonComponent, NotificationComponent],
  templateUrl: './renate-side-panel.component.html',
  styleUrl: './renate-side-panel.component.scss',
})
export class RenateSidePanelComponent implements AfterViewInit {
  @ViewChild('closeButtonSidePanel', { static: false })
  initialFocusedPanelElement?: ElementRef<HTMLElement>;

  @Output() panelClose: EventEmitter<void> = new EventEmitter<void>();

  notificationId = feedbackNotificationId;

  ngAfterViewInit() {
    this.initialFocusedPanelElement?.nativeElement.focus();
  }

  onClose() {
    this.panelClose.emit();
  }
}
