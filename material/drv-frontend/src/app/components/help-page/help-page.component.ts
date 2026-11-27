import { Component } from '@angular/core';
import { DetailsComponent } from '@drv-ds/drv-design-system-ng';

@Component({
  selector: 'drv-help-page',
  standalone: true,
  imports: [DetailsComponent],
  providers: [],
  templateUrl: './help-page.component.html',
})
export class HelpPageComponent {}
