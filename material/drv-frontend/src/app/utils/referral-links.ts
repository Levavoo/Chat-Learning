// Order matters: first matching pattern wins. Keep specific patterns before broader ones.
const REFERRAL_PATTERNS: [RegExp, string][] = [
  [/rentenbeginn-und-rentenhoehe|rentenrechner/i, 'Rentenrechner'],
  [/beratung-suchen-und-buchen|terminvereinbarung/i, 'Termin'],
  [/0800|kontakt.*telefon|servicetelefon/i, 'Servicetelefon'],
];

const SERVICE_PHONE_PATTERN = /\b0800[\s/-]?\d/;

export function classifyReferralLink(href: string): string | null {
  for (const [pattern, category] of REFERRAL_PATTERNS) {
    if (pattern.test(href)) {
      return category;
    }
  }
  return null;
}

// Accepts both markdown and HTML because ChatMessage.content is markdown while rendered message HTML has anchor tags.
export function detectReferralLinks(content: string): string[] {
  const categories = new Set<string>();

  const hrefRegex =
    /<a\b[^>]*\bhref\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s"'=<>`]+))[^>]*>/gi;
  let match: RegExpExecArray | null;
  while ((match = hrefRegex.exec(content)) !== null) {
    const href = match[1] ?? match[2] ?? match[3] ?? '';
    const category = classifyReferralLink(href);
    if (category) {
      categories.add(category);
    }
  }

  const markdownLinkStartRegex = /\[[^\]]*\]\(/g;
  while ((match = markdownLinkStartRegex.exec(content)) !== null) {
    const href = readMarkdownHref(content, match.index + match[0].length);
    if (!href) {
      continue;
    }
    const category = classifyReferralLink(href);
    if (category) {
      categories.add(category);
    }
  }

  // Only treat an actual service number as Servicetelefon, not arbitrary
  // substrings such as "10800 Euro" or a document name containing "A0800".
  if (
    !categories.has('Servicetelefon') &&
    SERVICE_PHONE_PATTERN.test(content)
  ) {
    categories.add('Servicetelefon');
  }

  return [...categories];
}

function readMarkdownHref(content: string, start: number): string | null {
  let depth = 1;
  let escaped = false;

  for (let index = start; index < content.length; index++) {
    const character = content[index];
    if (escaped) {
      escaped = false;
      continue;
    }
    if (character === '\\') {
      escaped = true;
      continue;
    }
    if (character === '(') {
      depth++;
    } else if (character === ')') {
      depth--;
      if (depth === 0) {
        return content.slice(start, index).trim();
      }
    }
  }

  return null;
}
