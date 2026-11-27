import { escapeHtml, sanitizeHtml } from './sanitize-html';

describe('sanitizeHtml', () => {
  describe('XSS payload removal', () => {
    it('should strip <script> tags', () => {
      const result = sanitizeHtml('<p>Hello</p><script>alert(1)</script>');
      expect(result).toBe('<p>Hello</p>');
    });

    it('should strip <img> with onerror handler', () => {
      const result = sanitizeHtml('<p>Text</p><img src=x onerror=alert(1)>');
      expect(result).toBe('<p>Text</p>');
    });

    it('should strip <svg> with onload handler', () => {
      const result = sanitizeHtml('<p>Text</p><svg onload=alert(1)></svg>');
      expect(result).toBe('<p>Text</p>');
    });

    it('should strip javascript: URLs from href', () => {
      const result = sanitizeHtml('<a href="javascript:alert(1)">click me</a>');
      expect(result).toBe('<a>click me</a>');
    });

    it('should strip data: URLs from href', () => {
      const result = sanitizeHtml(
        '<a href="data:text/html,<script>alert(1)</script>">click</a>',
      );
      expect(result).toBe('<a>click</a>');
    });

    it('should strip <iframe> tags', () => {
      const result = sanitizeHtml(
        '<p>Hello</p><iframe src="https://evil.com"></iframe>',
      );
      expect(result).toBe('<p>Hello</p>');
    });

    it('should strip <object> tags', () => {
      const result = sanitizeHtml(
        '<p>Hello</p><object data="evil.swf"></object>',
      );
      expect(result).toBe('<p>Hello</p>');
    });

    it('should strip <embed> tags', () => {
      const result = sanitizeHtml('<p>Hello</p><embed src="evil.swf">');
      expect(result).toBe('<p>Hello</p>');
    });

    it('should strip event handlers from allowed tags', () => {
      const result = sanitizeHtml('<p onclick="alert(1)">Hello</p>');
      expect(result).toBe('<p>Hello</p>');
    });

    it('should strip <form> tags', () => {
      const result = sanitizeHtml(
        '<form action="https://evil.com"><input type="text"></form>',
      );
      expect(result).toBe('');
    });

    it('should strip <meta> tags (http-equiv redirect)', () => {
      const result = sanitizeHtml(
        '<meta http-equiv="refresh" content="0;url=https://evil.com">',
      );
      expect(result).toBe('');
    });

    it('should strip obfuscated javascript: with mixed case', () => {
      const result = sanitizeHtml('<a href="JaVaScRiPt:alert(1)">click</a>');
      expect(result).toBe('<a>click</a>');
    });
  });

  describe('allowed content preservation', () => {
    it('should keep basic markdown HTML output', () => {
      const input =
        '<h1>Title</h1><p>Text with <strong>bold</strong> and <em>italic</em></p>';
      expect(sanitizeHtml(input)).toBe(input);
    });

    it('should keep links with safe attributes', () => {
      const input =
        '<a href="https://drv.de" target="_blank" rel="noopener noreferrer">DRV</a>';
      expect(sanitizeHtml(input)).toBe(input);
    });

    it('should keep lists', () => {
      const input = '<ul><li>Item 1</li><li>Item 2</li></ul>';
      expect(sanitizeHtml(input)).toBe(input);
    });

    it('should keep ordered lists', () => {
      const input = '<ol><li>First</li><li>Second</li></ol>';
      expect(sanitizeHtml(input)).toBe(input);
    });

    it('should keep code blocks', () => {
      const input = '<pre><code>const x = 1;</code></pre>';
      expect(sanitizeHtml(input)).toBe(input);
    });

    it('should keep tables', () => {
      const input =
        '<table><thead><tr><th>Header</th></tr></thead><tbody><tr><td>Cell</td></tr></tbody></table>';
      expect(sanitizeHtml(input)).toBe(input);
    });

    it('should keep spans with class attribute', () => {
      const input = '<span class="citation">Text</span>';
      expect(sanitizeHtml(input)).toBe(input);
    });

    it('should keep <br> tags', () => {
      const input = '<p>Line 1<br>Line 2</p>';
      expect(sanitizeHtml(input)).toBe(input);
    });

    it('should keep blockquotes', () => {
      const input = '<blockquote><p>Quote</p></blockquote>';
      expect(sanitizeHtml(input)).toBe(input);
    });

    it('should keep <del> for strikethrough', () => {
      const input = '<p><del>deleted</del> text</p>';
      expect(sanitizeHtml(input)).toBe(input);
    });

    it('should keep <hr> horizontal rules', () => {
      const input = '<p>Above</p><hr><p>Below</p>';
      expect(sanitizeHtml(input)).toBe(input);
    });
  });

  describe('edge cases', () => {
    it('should handle empty string', () => {
      expect(sanitizeHtml('')).toBe('');
    });

    it('should handle plain text without HTML', () => {
      expect(sanitizeHtml('Hello world')).toBe('Hello world');
    });

    it('should strip disallowed attributes from allowed tags', () => {
      const result = sanitizeHtml('<p style="color:red" id="x">Text</p>');
      expect(result).toBe('<p>Text</p>');
    });
  });
});

describe('escapeHtml', () => {
  it('should escape < and > characters', () => {
    expect(escapeHtml('<script>alert(1)</script>')).toBe(
      '&lt;script&gt;alert(1)&lt;/script&gt;',
    );
  });

  it('should escape & character', () => {
    expect(escapeHtml('foo & bar')).toBe('foo &amp; bar');
  });

  it('should escape quotes', () => {
    expect(escapeHtml('"hello" & \'world\'')).toBe(
      '&quot;hello&quot; &amp; &#039;world&#039;',
    );
  });

  it('should leave plain text unchanged', () => {
    expect(escapeHtml('Hello world')).toBe('Hello world');
  });

  it('should handle empty string', () => {
    expect(escapeHtml('')).toBe('');
  });
});
