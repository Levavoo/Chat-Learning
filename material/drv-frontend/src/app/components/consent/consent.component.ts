import { Component, OnInit } from '@angular/core';
import {
  ButtonbarComponent,
  ButtonComponent,
  RichtextComponent,
} from '@drv-ds/drv-design-system-ng';

@Component({
  selector: 'drv-consent',
  imports: [ButtonComponent, ButtonbarComponent, RichtextComponent],
  templateUrl: './consent.component.html',
  styleUrl: './consent.component.scss',
})
export class ConsentComponent implements OnInit {
  ngOnInit(): void {
    window.scroll({
      top: 0,
      left: 0,
      behavior: 'smooth',
    });
  }

  goToChat(): void {
    window.close();
  }

  onGoBackEnter(event: Event): void {
    event?.preventDefault();
    this.goToChat();
  }
}
