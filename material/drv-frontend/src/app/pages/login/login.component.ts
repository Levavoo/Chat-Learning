import { Component, inject, OnDestroy, OnInit } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { Router, RouterModule } from '@angular/router';
import { AuthService } from '@auth/auth.service';
import {
  ButtonComponent,
  PasswordComponent,
  TextinputComponent,
} from '@drv-ds/drv-design-system-ng';
import { Subscription } from 'rxjs';

@Component({
  selector: 'drv-login',
  standalone: true,
  imports: [
    FormsModule,
    RouterModule,
    TextinputComponent,
    ButtonComponent,
    PasswordComponent,
  ],
  templateUrl: './login.component.html',
  styleUrl: './login.component.scss',
})
export class LoginComponent implements OnInit, OnDestroy {
  credentials = { username: '', password: '' };
  hasError = false;
  isLoading = false;
  errorText = [{ message: 'Ungültige Anmeldedaten' }];
  ariaAttributes = {
    username: {
      label: 'Textfeld zum Eingeben Ihres Benutzernamens',
    },
    password: {
      label: 'Textfeld zum Eingeben Ihres Passworts',
    },
  };

  private subscription = new Subscription();

  private readonly authService: AuthService = inject(AuthService);
  private readonly router: Router = inject(Router);

  async ngOnInit() {
    const isAuthenticated = await this.authService.checkAuthStatus();
    if (isAuthenticated) {
      this.router.navigate(['/chat']);
    }
  }

  onSubmit() {
    this.isLoading = true;
    this.subscription.add(
      this.authService
        .login(this.credentials.username, this.credentials.password)
        .subscribe({
          next: (success) => {
            this.isLoading = false;
            this.hasError = !success;
          },
          error: () => {
            this.isLoading = false;
            this.hasError = true;
          },
        }),
    );
  }

  ngOnDestroy(): void {
    this.subscription.unsubscribe();
  }
}
