import { describe, expect, it } from 'vitest';
import { normalizeHtml, unescapeHtmlEntities } from '../src/normalizer/html.js';

describe('HTML Normalizer', () => {
  it('unescapes common HTML entities', () => {
    const raw = '&lt;div&gt;Tom &amp; Jerry &quot;Show&#39;s&quot; &copy; &#8364;&euro;&apos;&lt;/div&gt;';
    const cleaned = unescapeHtmlEntities(raw);
    expect(cleaned).toContain('<div>Tom & Jerry "Show\'s"');
  });

  it('strips scripts, styles, comments, and navigations while preserving headings and text', () => {
    const html = `
      <!DOCTYPE html>
      <html>
        <head>
          <title>Acme Corp | Startup Directory</title>
          <meta name="description" content="Acme builds AI rockets.">
          <style>body { font-family: sans-serif; }</style>
          <script>console.log("tracker");</script>
        </head>
        <body>
          <nav><a href="/home">Home</a><a href="/about">About</a></nav>
          <div class="cookie-banner">Please accept all cookies!</div>
          <header><h1>Acme Corporation</h1></header>
          <main>
            <h2>About Us</h2>
            <p>Acme is an aerospace startup with <strong>450 employees</strong>.</p>
            <div style="display:none">Internal hidden code</div>
            <p aria-hidden="true">Hidden accessibility text</p>
            <h3>Products</h3>
            <ul>
              <li>Falcon Rocket</li>
              <li>Star Booster</li>
            </ul>
          </main>
          <footer>Copyright 2026 Acme Corp. All rights reserved.</footer>
        </body>
      </html>
    `;

    const result = normalizeHtml(html);
    expect(result.title).toBe('Acme Corp | Startup Directory');
    expect(result.metadata?.['description']).toBe('Acme builds AI rockets.');
    expect(result.normalizedText).toContain('# Acme Corporation');
    expect(result.normalizedText).toContain('## About Us');
    expect(result.normalizedText).toContain('Acme is an aerospace startup with 450 employees.');
    expect(result.normalizedText).toContain('- Falcon Rocket');
    expect(result.normalizedText).toContain('- Star Booster');

    // Noise should be completely stripped
    expect(result.normalizedText).not.toContain('console.log');
    expect(result.normalizedText).not.toContain('font-family');
    expect(result.normalizedText).not.toContain('Please accept all cookies');
    expect(result.normalizedText).not.toContain('Internal hidden code');
    expect(result.normalizedText).not.toContain('Copyright 2026');
  });

  it('preserves and formats tables nicely', () => {
    const html = `
      <table>
        <thead>
          <tr><th>Product</th><th>Pricing</th><th>Tier</th></tr>
        </thead>
        <tbody>
          <tr><td>SuperApp</td><td>$29/mo</td><td>PAID</td></tr>
          <tr><td>Community</td><td>$0</td><td>FREE</td></tr>
        </tbody>
      </table>
    `;

    const result = normalizeHtml(html);
    expect(result.normalizedText).toContain('| Product | Pricing | Tier |');
    expect(result.normalizedText).toContain('| SuperApp | $29/mo | PAID |');
    expect(result.normalizedText).toContain('| Community | $0 | FREE |');
  });
});
