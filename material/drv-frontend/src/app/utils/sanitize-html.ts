import DOMPurify from 'dompurify';

// Tags needed for Markdown output via marked.
const ALLOWED_TAGS = [
  'p',
  'ul',
  'ol',
  'li',
  'a',
  'strong',
  'em',
  'code',
  'pre',
  'h1',
  'h2',
  'h3',
  'h4',
  'br',
  'span',
  'sup',
  'sub',
  'table',
  'thead',
  'tbody',
  'tr',
  'th',
  'td',
  'blockquote',
  'del',
  'hr',
];

const ALLOWED_ATTR = ['href', 'target', 'rel', 'class', 'title'];

export function escapeHtml(text: string): string {
  return text
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#039;');
}

// Must be called on all HTML before passing to `bypassSecurityTrustHtml`.
export function sanitizeHtml(dirty: string): string {
  return DOMPurify.sanitize(dirty, {
    ALLOWED_TAGS,
    ALLOWED_ATTR,
    FORCE_BODY: true,
  });
}
