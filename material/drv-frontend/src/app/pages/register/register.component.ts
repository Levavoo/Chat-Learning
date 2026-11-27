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
  selector: 'drv-register',
  standalone: true,
  imports: [
    FormsModule,
    RouterModule,
    TextinputComponent,
    ButtonComponent,
    PasswordComponent,
  ],
  templateUrl: './register.component.html',
  styleUrl: './register.component.scss',
})
export class RegisterComponent implements OnInit, OnDestroy {
  credentials = { username: '', email: '', password: '', confirmPassword: '' };
  hasError = false;
  isLoading = false;
  errorText = [{ message: 'Registrierung fehlgeschlagen' }];
  showConfirmation = false;
  confirmationCode = '';
  ariaAttributes = {
    username: {
      label: 'Textfeld zum Eingeben Ihres Benutzernamens',
    },
    email: {
      label: 'Textfeld zum Eingeben Ihrer E-Mail-Adresse',
    },
    password: {
      label: 'Textfeld zum Eingeben Ihres Passworts',
    },
    confirmPassword: {
      label: 'Textfeld zum Bestätigen Ihres Passworts',
    },
    confirmationCode: {
      label: 'Textfeld zum Eingeben des Bestätigungscodes',
    },
  };

  private subscriptions: Subscription[] = [];

  private readonly authService: AuthService = inject(AuthService);
  private readonly router: Router = inject(Router);

  async ngOnInit() {
    const isAuthenticated = await this.authService.checkAuthStatus();
    if (isAuthenticated) {
      this.router.navigate(['/chat']);
    }
  }

  onSubmit() {
    if (this.credentials.password !== this.credentials.confirmPassword) {
      this.hasError = true;
      this.errorText = [{ message: 'Passwörter stimmen nicht überein' }];
      return;
    }

    this.isLoading = true;
    this.hasError = false;

    this.subscriptions.push(
      this.authService
        .register(
          this.credentials.username,
          this.credentials.password,
          this.credentials.email,
        )
        .subscribe({
          next: (result) => {
            this.isLoading = false;
            if (result.success) {
              if (result.requiresConfirmation) {
                this.showConfirmation = true;
              } else {
                this.router.navigate(['/login']);
              }
            } else {
              this.hasError = true;
            }
          },
          error: () => {
            this.isLoading = false;
            this.hasError = true;
          },
        }),
    );
  }

  onConfirm() {
    this.isLoading = true;
    this.hasError = false;

    this.subscriptions.push(
      this.authService
        .confirmRegistration(this.credentials.username, this.confirmationCode)
        .subscribe({
          next: (success) => {
            this.isLoading = false;
            if (success) {
              this.router.navigate(['/login']);
            } else {
              this.hasError = true;
              this.errorText = [{ message: 'Ungültiger Bestätigungscode' }];
            }
          },
          error: () => {
            this.isLoading = false;
            this.hasError = true;
            this.errorText = [{ message: 'Bestätigung fehlgeschlagen' }];
          },
        }),
    );
  }

  get isFormValid(): boolean {
    return !!(
      this.credentials.username &&
      this.credentials.email &&
      this.credentials.password &&
      this.credentials.confirmPassword &&
      this.credentials.password === this.credentials.confirmPassword
    );
  }

  ngOnDestroy(): void {
    this.subscriptions.forEach((sub) => {
      sub.unsubscribe();
    });
  }
}
