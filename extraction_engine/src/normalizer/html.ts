/**
 * High-performance, intelligent HTML normalizer.
 * Strips noise, scripts, styles, boilerplate, and cookie banners while retaining
 * headings, tables, lists, and semantic text content.
 */

export interface NormalizationResult {
  normalizedText: string;
  originalLength: number;
  normalizedLength: number;
  title?: string;
  metadata?: Record<string, string>;
}

export function unescapeHtmlEntities(text: string): string {
  return text
    .replace(/&amp;/g, '&')
    .replace(/&lt;/g, '<')
    .replace(/&gt;/g, '>')
    .replace(/&quot;/g, '"')
    .replace(/&#39;/g, "'")
    .replace(/&apos;/g, "'")
    .replace(/&nbsp;/g, ' ')
    .replace(/&#(\d+);/g, (_, dec) => String.fromCharCode(Number(dec)))
    .replace(/&#x([0-9a-fA-F]+);/g, (_, hex) =>
      String.fromCharCode(parseInt(hex, 16))
    );
}

export function extractHtmlMetadata(html: string): {
  title?: string;
  metadata: Record<string, string>;
} {
  const metadata: Record<string, string> = {};

  // Extract <title>...</title>
  const titleMatch = html.match(/<title[^>]*>([\s\S]*?)<\/title>/i);
  const title = titleMatch && titleMatch[1] ? unescapeHtmlEntities(titleMatch[1].trim()) : undefined;

  // Extract meta tags: description, og:title, og:description, etc.
  const metaRegex = /<meta\s+[^>]*?(?:name|property)=["']([^"']+)["'][^>]*?content=["']([^"']*)["'][^>]*>/gi;
  let match: RegExpExecArray | null;
  while ((match = metaRegex.exec(html)) !== null) {
    const key = match[1]?.trim();
    const val = match[2]?.trim();
    if (key && val) {
      metadata[key] = unescapeHtmlEntities(val);
    }
  }

  return { title, metadata };
}

export function normalizeHtml(rawHtml: string): NormalizationResult {
  if (!rawHtml) {
    return {
      normalizedText: '',
      originalLength: 0,
      normalizedLength: 0,
    };
  }

  const originalLength = rawHtml.length;
  const { title, metadata } = extractHtmlMetadata(rawHtml);

  let text = rawHtml;

  // 1. Remove HTML comments
  text = text.replace(/<!--[\s\S]*?-->/g, ' ');

  // 2. Remove script, style, noscript, svg, iframe, canvas tags with their content
  text = text.replace(/<(script|style|noscript|svg|iframe|canvas|template)[^>]*>[\s\S]*?<\/\1>/gi, ' ');

  // 3. Remove navigation, footer, aside blocks
  text = text.replace(/<(nav|footer|aside)[^>]*>[\s\S]*?<\/\1>/gi, '\n');

  // 4. Remove elements with cookie, banner, consent, modal, or advertisement class/id
  text = text.replace(
    /<([a-z0-9]+)[^>]*?(?:class|id)=["'][^"']*(?:cookie|consent|banner|newsletter|advertisement|modal-backdrop|privacy-notice)[^"']*["'][^>]*>[\s\S]*?<\/\1>/gi,
    ' '
  );

  // 5. Remove hidden elements
  text = text.replace(
    /<([a-z0-9]+)[^>]*?(?:aria-hidden=["']true["']|style=["'][^"']*display:\s*none[^"']*["']|hidden)[^>]*>[\s\S]*?<\/\1>/gi,
    ' '
  );

  // 6. Convert headings to markdown-style markers
  text = text.replace(/<h1[^>]*>([\s\S]*?)<\/h1>/gi, '\n\n# $1\n\n');
  text = text.replace(/<h2[^>]*>([\s\S]*?)<\/h2>/gi, '\n\n## $1\n\n');
  text = text.replace(/<h3[^>]*>([\s\S]*?)<\/h3>/gi, '\n\n### $1\n\n');
  text = text.replace(/<h[4-6][^>]*>([\s\S]*?)<\/h[4-6]>/gi, '\n\n#### $1\n\n');

  // 7. Convert table cells and rows into readable structured text
  text = text.replace(/<tr[^>]*>([\s\S]*?)<\/tr>/gi, (_, rowContent) => {
    // Collect <th> or <td> inside row
    const cells: string[] = [];
    const cellRegex = /<(?:td|th)[^>]*>([\s\S]*?)<\/(?:td|th)>/gi;
    let cMatch: RegExpExecArray | null;
    while ((cMatch = cellRegex.exec(rowContent)) !== null) {
      const cellText = (cMatch[1] || '')
        .replace(/<[^>]+>/g, ' ')
        .replace(/\s+/g, ' ')
        .trim();
      cells.push(cellText);
    }
    return cells.length > 0 ? `\n| ${cells.join(' | ')} |` : '\n';
  });

  // 8. Convert list items: <li>...</li> -> \n- ...
  text = text.replace(/<li[^>]*>([\s\S]*?)<\/li>/gi, '\n- $1');

  // 9. Convert definition lists: <dt> -> \n, <dd> -> : ...
  text = text.replace(/<dt[^>]*>([\s\S]*?)<\/dt>/gi, '\n$1: ');
  text = text.replace(/<dd[^>]*>([\s\S]*?)<\/dd>/gi, '$1\n');

  // 10. Convert block tags into newlines
  text = text.replace(/<(?:p|div|section|article|blockquote|header)[^>]*>/gi, '\n\n');
  text = text.replace(/<\/(?:p|div|section|article|blockquote|header)>/gi, '\n');
  text = text.replace(/<br\s*\/?>/gi, '\n');
  text = text.replace(/<hr\s*\/?>/gi, '\n---\n');

  // 11. Strip all remaining HTML tags
  text = text.replace(/<[^>]+>/g, ' ');

  // 12. Unescape HTML entities
  text = unescapeHtmlEntities(text);

  // 13. Collapse spaces before punctuation
  text = text.replace(/[ \t]+([.,;:!?])/g, '$1');

  // 13. Clean whitespace: collapse multiple horizontal spaces, normalize newlines
  text = text
    .split('\n')
    .map((line) => line.replace(/[ \t]+/g, ' ').trim())
    .filter((line, idx, arr) => {
      // Remove consecutive empty lines (keep at most 2 newlines)
      if (line === '' && arr[idx - 1] === '') {
        return false;
      }
      return true;
    })
    .join('\n')
    .trim();

  // Prepend title and key metadata if extracted and not already present
  const headerParts: string[] = [];
  if (title) {
    headerParts.push(`Document Title: ${title}`);
  }
  if (metadata['description']) {
    headerParts.push(`Description: ${metadata['description']}`);
  }

  const finalText = headerParts.length > 0 ? `${headerParts.join('\n')}\n\n${text}` : text;

  return {
    normalizedText: finalText,
    originalLength,
    normalizedLength: finalText.length,
    title,
    metadata,
  };
}
