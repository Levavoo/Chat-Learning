import { classifyReferralLink, detectReferralLinks } from './referral-links';

describe('classifyReferralLink', () => {
  it('should classify Rentenrechner URL', () => {
    expect(
      classifyReferralLink(
        'https://www.deutsche-rentenversicherung.de/DRV/DE/Online-Dienste/rentenbeginn-und-rentenhoehe',
      ),
    ).toBe('Rentenrechner');
  });

  it('should classify rentenrechner keyword', () => {
    expect(classifyReferralLink('https://example.com/rentenrechner')).toBe(
      'Rentenrechner',
    );
  });

  it('should classify Termin URL (beratung-suchen-und-buchen)', () => {
    expect(
      classifyReferralLink(
        'https://www.deutsche-rentenversicherung.de/DRV/DE/beratung-suchen-und-buchen',
      ),
    ).toBe('Termin');
  });

  it('should classify Termin URL (Terminvereinbarung)', () => {
    expect(classifyReferralLink('https://example.com/Terminvereinbarung')).toBe(
      'Termin',
    );
  });

  it('should classify Servicetelefon URL (0800)', () => {
    expect(classifyReferralLink('tel:0800-1000-4800')).toBe('Servicetelefon');
  });

  it('should classify Servicetelefon URL (kontakt/telefon)', () => {
    expect(classifyReferralLink('https://example.com/kontakt/telefon')).toBe(
      'Servicetelefon',
    );
  });

  it('should classify servicetelefon keyword', () => {
    expect(classifyReferralLink('https://example.com/servicetelefon')).toBe(
      'Servicetelefon',
    );
  });

  it('should return null for non-matching URL', () => {
    expect(
      classifyReferralLink(
        'https://www.deutsche-rentenversicherung.de/DRV/DE/Startseite',
      ),
    ).toBeNull();
  });

  it('should return null for empty string', () => {
    expect(classifyReferralLink('')).toBeNull();
  });
});

describe('detectReferralLinks', () => {
  it('should detect Rentenrechner link in HTML', () => {
    const html =
      '<p>Berechnen Sie Ihre Rente: <a href="https://example.com/rentenbeginn-und-rentenhoehe">Rentenrechner</a></p>';
    expect(detectReferralLinks(html)).toEqual(['Rentenrechner']);
  });

  it('should detect multiple categories', () => {
    const html =
      '<a href="https://example.com/rentenrechner">Rechner</a> und <a href="https://example.com/beratung-suchen-und-buchen">Termin</a>';
    const result = detectReferralLinks(html);
    expect(result).toContain('Rentenrechner');
    expect(result).toContain('Termin');
    expect(result.length).toBe(2);
  });

  it('should detect Servicetelefon via 0800 in plain text', () => {
    const html = '<p>Rufen Sie uns an: 0800 1000 4800</p>';
    expect(detectReferralLinks(html)).toEqual(['Servicetelefon']);
  });

  it('should deduplicate same category', () => {
    const html =
      '<a href="https://a.com/rentenrechner">A</a><a href="https://b.com/rentenrechner">B</a>';
    expect(detectReferralLinks(html)).toEqual(['Rentenrechner']);
  });

  it('should return empty array for no referral links', () => {
    const html = '<p>Hallo Welt <a href="https://example.com">Link</a></p>';
    expect(detectReferralLinks(html)).toEqual([]);
  });

  it('should detect markdown-style referral links', () => {
    const content =
      'Berechnen Sie Ihre Rente: [Rentenrechner](https://example.com/rentenbeginn-und-rentenhoehe)';
    expect(detectReferralLinks(content)).toEqual(['Rentenrechner']);
  });

  it('should not classify arbitrary 0800 substrings as Servicetelefon', () => {
    expect(detectReferralLinks('Ihre Rente beträgt etwa 10800 Euro.')).toEqual(
      [],
    );
    expect(
      detectReferralLinks('Die Broschüre A0800 behandelt dieses Thema.'),
    ).toEqual([]);
  });

  it('should detect a markdown referral link whose URL contains parentheses', () => {
    const content =
      '[Rentenrechner](https://example.com/rentenrechner?range=(1))';
    expect(detectReferralLinks(content)).toEqual(['Rentenrechner']);
  });

  it('should detect referral links with single-quoted HTML hrefs', () => {
    const content =
      "<a class='referral' href='https://example.com/Terminvereinbarung'>Termin</a>";
    expect(detectReferralLinks(content)).toEqual(['Termin']);
  });

  it('should return no referral for an incomplete service number', () => {
    expect(detectReferralLinks('Kontakt: 0800')).toEqual([]);
  });
});
