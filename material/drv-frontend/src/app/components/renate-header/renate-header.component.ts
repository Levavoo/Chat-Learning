import { CommonModule } from '@angular/common';
import { Component, inject } from '@angular/core';
import { AuthService } from '@auth/auth.service';
import { environment } from 'src/environments/environment';
import { TooltipComponent } from '@drv-ds/drv-design-system-ng';

@Component({
  selector: 'drv-renate-header',
  imports: [CommonModule, TooltipComponent],
  templateUrl: './renate-header.component.html',
  styleUrl: './renate-header.component.scss',
})
export class RenateHeaderComponent {
  private readonly authService: AuthService = inject(AuthService);

  isAuthenticated$ = this.authService.isAuthenticated$;
  isReview = environment.showReviewTag;

  onLogout() {
    this.authService.logout();
  }
}
