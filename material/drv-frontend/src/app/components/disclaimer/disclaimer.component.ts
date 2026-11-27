import { Component, OnInit } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { DisclaimerTextComponent } from '@components/disclaimer-text/disclaimer-text.component';
import {
  ButtonbarComponent,
  ButtonComponent,
  RichtextComponent,
} from '@drv-ds/drv-design-system-ng';

@Component({
  selector: 'drv-disclaimer',
  imports: [
    FormsModule,
    ButtonComponent,
    ButtonbarComponent,
    RichtextComponent,
    DisclaimerTextComponent,
  ],
  templateUrl: './disclaimer.component.html',
  styleUrl: './disclaimer.component.scss',
})
export class DisclaimerComponent implements OnInit {
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
