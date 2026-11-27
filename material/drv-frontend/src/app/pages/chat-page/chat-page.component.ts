import { Component } from '@angular/core';
import { ChatbotComponent } from '@components/chatbot/chatbot.component';
import { RenateHeaderComponent } from '@components/renate-header/renate-header.component';
import { FeedbackService } from '@services/feedback/feedback.service';

@Component({
  standalone: true,
  selector: 'drv-chat-page',
  templateUrl: './chat-page.component.html',
  styleUrl: './chat-page.component.scss',
  providers: [FeedbackService],
  imports: [ChatbotComponent, RenateHeaderComponent],
})
export class ChatPageComponent {}
