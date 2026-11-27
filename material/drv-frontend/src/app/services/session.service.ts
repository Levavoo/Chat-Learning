import { Injectable } from '@angular/core';
import { v4 as uuidv4 } from 'uuid';

@Injectable({
  providedIn: 'root',
})
export class SessionService {
  private currentSessionId: string | null = null;

  constructor() {
    this.createNewSession();
  }

  getSessionId(): string {
    if (!this.currentSessionId) {
      this.createNewSession();
    }
    return this.currentSessionId!;
  }

  createNewSession(): string {
    this.currentSessionId = uuidv4();
    return this.currentSessionId;
  }
}
