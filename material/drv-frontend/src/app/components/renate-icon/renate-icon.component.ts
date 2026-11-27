import { Component, Input } from '@angular/core';

@Component({
  selector: 'drv-renate-icon',
  imports: [],
  templateUrl: './renate-icon.component.html',
  styleUrl: './renate-icon.component.scss',
})
export class RenateIconComponent {
  @Input()
  size = 48;
}
