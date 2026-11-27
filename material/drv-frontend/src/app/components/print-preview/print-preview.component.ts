import { Component, ElementRef, inject, AfterViewInit } from '@angular/core';
import { DisclaimerTextComponent } from '@components/disclaimer-text/disclaimer-text.component';
import { PrintableChatMessageComponent } from '@components/printable-chat-message/printable-chat-message.component';
import {
  HeaderComponent,
  RichtextComponent,
} from '@drv-ds/drv-design-system-ng';
import { ChatMessage } from '@models/bedrock-chat.models';
import { BedrockChatService } from '@services/bedrock-chat/bedrock-chat.service';

@Component({
  selector: 'drv-print-preview',
  standalone: true,
  imports: [
    PrintableChatMessageComponent,
    RichtextComponent,
    HeaderComponent,
    DisclaimerTextComponent,
  ],
  templateUrl: './print-preview.component.html',
  styleUrl: './print-preview.component.scss',
})
export class PrintPreviewComponent implements AfterViewInit {
  private el = inject(ElementRef);
  public date: string = new Date()
    .toLocaleDateString()
    .concat(' - ', new Date().toLocaleTimeString(), ' Uhr');

  private bedrockChatService = inject(BedrockChatService);

  getChatMessages(): ChatMessage[] {
    return this.bedrockChatService.chatMessages;
  }

  ngAfterViewInit() {
    const disclaimer = this.el.nativeElement.querySelector('.print-disclaimer');
    if (disclaimer) {
      disclaimer.innerHTML = disclaimer.innerHTML.replace(
        /<\/a>\s*\)/g,
        ')</a> ',
      );
    }
  }
}
