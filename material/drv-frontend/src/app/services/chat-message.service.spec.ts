import { TestBed } from '@angular/core/testing';

import { ChatSource } from '@models/bedrock-chat.models';
import { ChatMessageService } from './chat-message.service';
import { DomSanitizer } from '@angular/platform-browser';

import { provideHttpClientTesting } from '@angular/common/http/testing';

import { provideHttpClient } from '@angular/common/http';
import { ApiProxyService } from './api-proxy/api-proxy.service';
import { SecurityContext } from '@angular/core';

describe('ChatMessageService', () => {
  let service: ChatMessageService;
  let sanitizer: DomSanitizer;
  const apiProxyServiceMock = {
    conversationUrl: 'http://mock-api.conversation',
  };

  beforeEach(() => {
    TestBed.configureTestingModule({
      providers: [
        provideHttpClient(),
        provideHttpClientTesting(),
        { provide: ApiProxyService, useValue: apiProxyServiceMock },
      ],
    });
    service = TestBed.inject(ChatMessageService);
    sanitizer = TestBed.inject(DomSanitizer);
  });

  it('should be created', () => {
    expect(service).toBeTruthy();
  });

  describe('convertToHtml()', () => {
    it('should return empty string for empty/null input', async () => {
      const expected = sanitizer.bypassSecurityTrustHtml('');
      spyOn(service, 'convertToHtml').and.returnValue(
        Promise.resolve(expected),
      );
      const result = await service.convertToHtml('');

      expect(result).toBe(expected);
    });

    it('should replace url to anchor tag', async () => {
      const input = 'Check this: \\url{https://example.com}';
      const expected = sanitizer.bypassSecurityTrustHtml(input);
      spyOn(service, 'convertToHtml').and.returnValue(
        Promise.resolve(expected),
      );
      const result = await service.convertToHtml(input);

      expect(result).toBe(expected);
    });

    it('should replace href with label and index', async () => {
      const input = 'Check this: \\href{https://test.com}{Test Label}{meta}';
      const expected = sanitizer.bypassSecurityTrustHtml(input);
      spyOn(service, 'convertToHtml').and.returnValue(
        Promise.resolve(expected),
      );
      const result = await service.convertToHtml(input);
      expect(result).toBe(expected);
    });

    it('should replace [number]', async () => {
      const input = 'Example[2] and test [15]';
      const expected = '<p>Example and test</p>';
      const result = await service.convertToHtml(input);

      const plain = sanitizer.sanitize(SecurityContext.HTML, result);

      expect(plain?.trim()).toBe(expected);
    });
  });

  describe('extractSources()', () => {
    it('should return empty array for empty or null input', () => {
      expect(service.extractSources('')).toEqual([]);
      expect(service.extractSources(null as unknown as string)).toEqual([]);
    });

    it('should extract a single href entry', () => {
      const input = 'See \\href{https://example.com}{Example}{An example site}';
      const result = service.extractSources(input);
      const output = [
        {
          index: '1',
          url: 'https://example.com',
          label: 'Example',
          description: 'An example site',
        },
      ];

      expect(result).toEqual(output);
    });

    it('should extract multiple href entries and increment indices', () => {
      const input =
        'First: \\href{http://a.com}{A}{First link} then \\href{https://b.org}{B}{Second link}';
      const result = service.extractSources(input);
      const output = [
        {
          index: '1',
          url: 'http://a.com',
          label: 'A',
          description: 'First link',
        },
        {
          index: '2',
          url: 'https://b.org',
          label: 'B',
          description: 'Second link',
        },
      ];

      expect(result).toEqual(output);
    });

    it('should ignore text without href patterns', () => {
      const input = 'Just some plain text without any sources.';
      const result = service.extractSources(input);
      const output: ChatSource[] = [];

      expect(result).toEqual(output);
    });

    it('should handle href mixed with other text', () => {
      const input =
        'Intro text \\href{https://test.com}{Label}{Desc} outro text';
      const result = service.extractSources(input);
      const output = [
        {
          index: '1',
          url: 'https://test.com',
          label: 'Label',
          description: 'Desc',
        },
      ];

      expect(result).toEqual(output);
    });
  });
});
