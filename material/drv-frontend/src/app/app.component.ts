import { HttpClient } from '@angular/common/http';
import { AfterViewInit, Component, OnInit } from '@angular/core';
import { RouterOutlet } from '@angular/router';
import {
  ButtonComponent,
  FooterComponent,
  HeaderComponent,
  BlankpageComponent,
  FooterLinkItem,
} from '@drv-ds/drv-design-system-ng';

@Component({
  selector: 'drv-root',
  standalone: true,
  imports: [
    RouterOutlet,
    FooterComponent,
    HeaderComponent,
    ButtonComponent,
    BlankpageComponent,
  ],
  providers: [HttpClient],
  templateUrl: './app.component.html',
  styleUrl: './app.component.scss',
})
export class AppComponent implements OnInit, AfterViewInit {
  title = 'frontend-digibro';
  breadcrumbItems = [];
  copyrightString = '';
  navigationButtons: FooterLinkItem[] = [
    {
      href: 'https://www.deutsche-rentenversicherung.de/DRV/DE/Service/Footer/Impressum/impressum_node.html',
      text: 'Impressum',
      htmltarget: '_blank',
      htmltitle: '(Es öffnet sich eine neue Seite)',
    },
    {
      href: 'https://www.deutsche-rentenversicherung.de/DRV/DE/Service/Footer/Datenschutz/datenschutz_node.html',
      text: 'Datenschutz',
      htmltarget: '_blank',
      htmltitle: '(Es öffnet sich eine neue Seite)',
    },
    {
      href: '/#/disclaimer',
      text: 'Nutzungsbedingungen',
      htmltarget: '_blank',
      htmltitle: '(Es öffnet sich eine neue Seite)',
    },
    {
      href: 'https://www.deutsche-rentenversicherung.de/renate-barrierefreiheit',
      text: 'Barrierefreiheit',
      htmltarget: '_blank',
      htmltitle: '(Es öffnet sich eine neue Seite)',
    },
    {
      href: 'https://deutsche-rentenversicherung.de/renate-gebaerdensprachfilm',
      text: 'DGS',
      htmltarget: '_blank',
      htmltitle: 'Deutsche Gebärdensprache (Es öffnet sich eine neue Seite)',
      icon: 'sign-language',
    },
    {
      href: 'https://deutsche-rentenversicherung.de/renate-leichte-sprache',
      text: 'Leichte Sprache',
      htmltarget: '_blank',
      htmltitle: '(Es öffnet sich eine neue Seite)',
      icon: 'easy-language',
    },
  ];
  ngOnInit(): void {
    const currentYear = new Date().getFullYear();
    this.copyrightString = '© Deutsche Rentenversicherung ' + currentYear;
    const currentTheme = localStorage.getItem('theme');
    if (!currentTheme) {
      localStorage.setItem('theme', 'light');
    }

    if (currentTheme == 'dark') {
      document.body.classList.add('drv-theme--dark');
    } else {
      document.body.classList.remove('drv-theme--dark');
    }
  }

  ngAfterViewInit() {
    const darkToggle = document.querySelector('span.drv-toggle__state');
    if (!darkToggle) {
      return;
    }

    darkToggle.addEventListener('click', function () {
      localStorage.setItem(
        'theme',
        localStorage.getItem('theme') === 'dark' ? 'light' : 'dark',
      );
    });
  }
}
