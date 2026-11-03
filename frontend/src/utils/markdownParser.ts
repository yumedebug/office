import type { JSONContent } from '@tiptap/core';
import type { SlideData } from '../types';
import { createSlideId } from './converters';

/* ------------------------------------------------------------------ */
/* Inline parsing                                                      */
/* ------------------------------------------------------------------ */

const INLINE_RE =
  /(\*\*[^*\n]+\*\*|__[^_\n]+__|~~[^~\n]+~~|\*[^*\n]+\*|_[^_\n]+_|`[^`\n]+`|\[[^\]\n]*\]\([^)\n]*\))/g;

const SAFE_LINK = /^(https?:\/\/|mailto:)/i;

function sanitizeHref(href: string): string {
  const value = href.trim();
  return SAFE_LINK.test(value) ? value : '#';
}

function tokenToNode(token: string): JSONContent | null {
  const text = (value: string): JSONContent => ({ type: 'text', text: value });

  if (token.startsWith('**') && token.endsWith('**')) {
    return { type: 'text', text: token.slice(2, -2), marks: [{ type: 'bold' }] };
  }
  if (token.startsWith('__') && token.endsWith('__')) {
    return { type: 'text', text: token.slice(2, -2), marks: [{ type: 'bold' }] };
  }
  if (token.startsWith('~~') && token.endsWith('~~')) {
    return { type: 'text', text: token.slice(2, -2), marks: [{ type: 'strike' }] };
  }
  if (token.startsWith('`') && token.endsWith('`') && token.length > 2) {
    return { type: 'text', text: token.slice(1, -1), marks: [{ type: 'code' }] };
  }
  if (token.startsWith('*') && token.endsWith('*') && token.length > 2) {
    return { type: 'text', text: token.slice(1, -1), marks: [{ type: 'italic' }] };
  }
  if (token.startsWith('_') && token.endsWith('_') && token.length > 2) {
    return { type: 'text', text: token.slice(1, -1), marks: [{ type: 'italic' }] };
  }
  const link = /^\[([^\]]*)\]\(([^)]*)\)$/.exec(token);
  if (link) {
    const label = link[1].trim();
    const href = sanitizeHref(link[2]);
    if (!label) {
      return text(href);
    }
    if (href === '#') {
      return text(label);
    }
    return {
      type: 'text',
      text: label,
      marks: [{ type: 'link', attrs: { href, target: '_blank', rel: 'noopener noreferrer' } }],
    };
  }
  return null;
}

/** Convert one line of Markdown into Tiptap text nodes (never raw HTML). */
export function parseInline(input: string): JSONContent[] {
  const text = String(input ?? '');
  if (!text) {
    return [];
  }
  const nodes: JSONContent[] = [];
  const pattern = new RegExp(INLINE_RE.source, 'g');
  let cursor = 0;
  let match: RegExpExecArray | null;

  while ((match = pattern.exec(text)) !== null) {
    if (match.index > cursor) {
      nodes.push({ type: 'text', text: text.slice(cursor, match.index) });
    }
    const node = tokenToNode(match[0]);
    if (node) {
      nodes.push(node);
    } else {
      nodes.push({ type: 'text', text: match[0] });
    }
    cursor = match.index + match[0].length;
  }
  if (cursor < text.length) {
    nodes.push({ type: 'text', text: text.slice(cursor) });
  }
  return nodes;
}

function paragraph(input: string): JSONContent {
  const content = parseInline(input);
  return content.length ? { type: 'paragraph', content } : { type: 'paragraph' };
}

/* ------------------------------------------------------------------ */
/* Block parsing                                                       */
/* ------------------------------------------------------------------ */

const HEADING_RE = /^(#{1,6})\s+(.+?)\s*$/;
const BULLET_RE = /^\s*[-*+]\s+(.+)$/;
const ORDERED_RE = /^\s*\d+[.)]\s+(.+)$/;
const QUOTE_RE = /^\s*>\s?(.*)$/;
const HR_RE = /^(-{3,}|\*{3,}|_{3,})$/;

/** Convert Markdown into an array of Tiptap nodes. */
export function markdownToNodes(markdown: string): JSONContent[] {
  const lines = String(markdown ?? '')
    .replace(/\r\n?/g, '\n')
    .split('\n');
  const nodes: JSONContent[] = [];
  let index = 0;

  while (index < lines.length) {
    const line = lines[index];
    const trimmed = line.trim();

    if (!trimmed) {
      index += 1;
      continue;
    }

    if (trimmed.startsWith('```')) {
      const language = trimmed.slice(3).trim();
      index += 1;
      const buffer: string[] = [];
      while (index < lines.length && !lines[index].trim().startsWith('```')) {
        buffer.push(lines[index]);
        index += 1;
      }
      index += 1;
      const node: JSONContent = { type: 'codeBlock' };
      if (language) {
        node.attrs = { language };
      }
      if (buffer.length) {
        node.content = [{ type: 'text', text: buffer.join('\n') }];
      }
      nodes.push(node);
      continue;
    }

    const heading = HEADING_RE.exec(trimmed);
    if (heading) {
      nodes.push({
        type: 'heading',
        attrs: { level: heading[1].length },
        content: parseInline(heading[2]),
      });
      index += 1;
      continue;
    }

    if (HR_RE.test(trimmed)) {
      nodes.push({ type: 'horizontalRule' });
      index += 1;
      continue;
    }

    if (QUOTE_RE.test(trimmed)) {
      const buffer: string[] = [];
      while (index < lines.length && QUOTE_RE.test(lines[index].trim())) {
        const quoted = QUOTE_RE.exec(lines[index].trim());
        buffer.push(quoted ? quoted[1] : '');
        index += 1;
      }
      nodes.push({
        type: 'blockquote',
        content: buffer.map((entry) => paragraph(entry)),
      });
      continue;
    }

    // Markdown table -> one paragraph per row (Tiptap StarterKit has no table
    // extension; the spreadsheet conversion handles real tables).
    if (trimmed.includes('|') && index + 1 < lines.length && isTableSeparator(lines[index + 1])) {
      nodes.push(paragraph(splitTableRow(lines[index]).join('  |  ')));
      index += 2;
      while (index < lines.length && lines[index].includes('|') && lines[index].trim()) {
        if (!isTableSeparator(lines[index])) {
          nodes.push(paragraph(splitTableRow(lines[index]).join('  |  ')));
        }
        index += 1;
      }
      continue;
    }

    if (BULLET_RE.test(line)) {
      const items: JSONContent[] = [];
      while (index < lines.length) {
        const bullet = BULLET_RE.exec(lines[index]);
        if (!bullet) {
          break;
        }
        items.push({ type: 'listItem', content: [paragraph(bullet[1])] });
        index += 1;
      }
      nodes.push({ type: 'bulletList', content: items });
      continue;
    }

    if (ORDERED_RE.test(line)) {
      const items: JSONContent[] = [];
      while (index < lines.length) {
        const ordered = ORDERED_RE.exec(lines[index]);
        if (!ordered) {
          break;
        }
        items.push({ type: 'listItem', content: [paragraph(ordered[1])] });
        index += 1;
      }
      nodes.push({ type: 'orderedList', attrs: { start: 1 }, content: items });
      continue;
    }

    nodes.push(paragraph(trimmed));
    index += 1;
  }

  return nodes;
}

/** Convert Markdown into a complete Tiptap document. */
export function markdownToDocument(markdown: string): JSONContent {
  const content = markdownToNodes(markdown);
  return { type: 'doc', content: content.length ? content : [{ type: 'paragraph' }] };
}

/* ------------------------------------------------------------------ */
/* Table detection                                                     */
/* ------------------------------------------------------------------ */

export type TableKind = 'markdown' | 'csv' | 'tsv';

export interface ParsedTable {
  rows: string[][];
  kind: TableKind;
}

function stripFences(text: string): string {
  const lines = text.replace(/\r\n?/g, '\n').split('\n');
  let start = 0;
  let end = lines.length;
  while (start < end && !lines[start].trim()) {
    start += 1;
  }
  while (end > start && !lines[end - 1].trim()) {
    end -= 1;
  }
  if (end - start >= 2) {
    const first = lines[start].trim();
    const last = lines[end - 1].trim();
    if (first.startsWith('```') && last.startsWith('```')) {
      return lines.slice(start + 1, end - 1).join('\n');
    }
  }
  return lines.slice(start, end).join('\n');
}

function splitTableRow(line: string): string[] {
  let text = line.trim();
  if (text.startsWith('|')) {
    text = text.slice(1);
  }
  if (text.endsWith('|')) {
    text = text.slice(0, -1);
  }
  return text.split('|').map((cell) => cell.trim().replace(/\\\|/g, '|'));
}

function isTableSeparator(line: string): boolean {
  if (!line || !line.includes('|')) {
    return false;
  }
  const cells = splitTableRow(line);
  if (cells.length < 2) {
    return false;
  }
  return cells.every((cell) => /^:?-{2,}:?$/.test(cell.replace(/\s+/g, '')));
}

function rectangular(rows: string[][]): string[][] {
  const width = rows.reduce((max, row) => Math.max(max, row.length), 0);
  return rows.map((row) => {
    const copy = row.slice();
    while (copy.length < width) {
      copy.push('');
    }
    return copy;
  });
}

function parseMarkdownTable(lines: string[]): string[][] | null {
  for (let index = 1; index < lines.length; index += 1) {
    if (!isTableSeparator(lines[index])) {
      continue;
    }
    if (!lines[index - 1].includes('|')) {
      continue;
    }
    const rows: string[][] = [splitTableRow(lines[index - 1])];
    let cursor = index + 1;
    while (cursor < lines.length && lines[cursor].includes('|') && lines[cursor].trim()) {
      if (!isTableSeparator(lines[cursor])) {
        rows.push(splitTableRow(lines[cursor]));
      }
      cursor += 1;
    }
    if (rows[0].length < 2 || rows.length < 1) {
      return null;
    }
    return rectangular(rows);
  }
  return null;
}

function parseDelimited(lines: string[], delimiter: string): string[][] | null {
  if (lines.length < 2) {
    return null;
  }
  const rows = lines.map((line) => line.split(delimiter).map((cell) => cell.trim()));
  const width = rows[0].length;
  if (width < 2) {
    return null;
  }
  if (!rows.every((row) => row.length === width)) {
    return null;
  }
  return rectangular(rows);
}

/** Parse RFC 4180 style CSV text (quoted fields, embedded newlines). */
export function parseCsvText(text: string): string[][] {
  const rows: string[][] = [];
  let row: string[] = [];
  let field = '';
  let inQuotes = false;

  for (let index = 0; index < text.length; index += 1) {
    const character = text[index];
    if (inQuotes) {
      if (character === '"') {
        if (text[index + 1] === '"') {
          field += '"';
          index += 1;
        } else {
          inQuotes = false;
        }
      } else {
        field += character;
      }
      continue;
    }
    if (character === '"') {
      inQuotes = true;
    } else if (character === ',') {
      row.push(field);
      field = '';
    } else if (character === '\n') {
      row.push(field);
      rows.push(row);
      row = [];
      field = '';
    } else if (character !== '\r') {
      field += character;
    }
  }
  row.push(field);
  rows.push(row);

  return rows
    .map((entry) => entry.map((cell) => cell.trim()))
    .filter((entry) => entry.some((cell) => cell !== ''));
}

function parseCsvBlock(lines: string[]): string[][] | null {
  if (lines.length < 2) {
    return null;
  }
  const rows = parseCsvText(lines.join('\n'));
  if (rows.length < 2) {
    return null;
  }
  const width = rows[0].length;
  if (width < 2 || !rows.every((row) => row.length === width)) {
    return null;
  }
  return rectangular(rows);
}

/**
 * Detect a Markdown table, TSV block or CSV block.
 * Returns ``null`` when the text is not a table.
 */
export function parseTable(input: string): ParsedTable | null {
  const stripped = stripFences(String(input ?? ''));
  if (!stripped.trim()) {
    return null;
  }
  const lines = stripped
    .split('\n')
    .map((line) => line.replace(/\s+$/, ''))
    .filter((line) => line.trim().length > 0);

  const markdown = parseMarkdownTable(lines);
  if (markdown) {
    return { rows: markdown, kind: 'markdown' };
  }

  const tsv = parseDelimited(lines, '\t');
  if (tsv) {
    return { rows: tsv, kind: 'tsv' };
  }

  const csv = parseCsvBlock(lines);
  if (csv) {
    return { rows: csv, kind: 'csv' };
  }

  return null;
}

/* ------------------------------------------------------------------ */
/* Slides                                                              */
/* ------------------------------------------------------------------ */

function plainInline(input: string): string {
  return String(input ?? '')
    .replace(/!\[([^\]]*)\]\([^)]*\)/g, '$1')
    .replace(/\[([^\]]*)\]\([^)]*\)/g, '$1')
    .replace(/(\*\*|__)(.*?)\1/g, '$2')
    .replace(/(\*|_)(.*?)\1/g, '$2')
    .replace(/~~(.*?)~~/g, '$1')
    .replace(/`([^`]*)`/g, '$1')
    .trim();
}

function plainBlock(lines: string[]): string {
  const output: string[] = [];
  for (const line of lines) {
    const trimmed = line.trim();
    if (!trimmed) {
      if (output.length && output[output.length - 1] !== '') {
        output.push('');
      }
      continue;
    }
    const bullet = /^\s*[-*+]\s+(.*)$/.exec(trimmed);
    if (bullet) {
      output.push(`• ${plainInline(bullet[1])}`);
      continue;
    }
    const ordered = /^\s*\d+[.)]\s+(.*)$/.exec(trimmed);
    if (ordered) {
      output.push(`• ${plainInline(ordered[1])}`);
      continue;
    }
    if (HEADING_RE.test(trimmed)) {
      continue;
    }
    output.push(plainInline(trimmed));
  }
  while (output.length && output[output.length - 1] === '') {
    output.pop();
  }
  return output.join('\n');
}

const MAX_GENERATED_SLIDES = 60;

/**
 * Turn a Markdown answer into slides.
 * Level 1-3 headings start new slides; deeper headings stay in the body.
 */
export function markdownToSlides(markdown: string): SlideData[] {
  const lines = String(markdown ?? '')
    .replace(/\r\n?/g, '\n')
    .split('\n');

  interface Section {
    title: string;
    level: number;
    body: string[];
  }

  const sections: Section[] = [];
  let current: Section | null = null;
  const preamble: string[] = [];

  for (const raw of lines) {
    const line = raw.trim();
    const heading = HEADING_RE.exec(line);
    if (heading && heading[1].length <= 3) {
      current = { title: plainInline(heading[2]), level: heading[1].length, body: [] };
      sections.push(current);
      continue;
    }
    if (current) {
      current.body.push(raw);
    } else if (line) {
      preamble.push(line);
    }
  }

  const slides: SlideData[] = [];

  if (sections.length === 0) {
    const text = plainBlock(lines);
    if (!text) {
      return [];
    }
    const parts = text.split('\n');
    const title = parts[0].slice(0, 90);
    const body = parts.slice(1).join('\n').trim();
    slides.push({
      id: createSlideId(),
      title,
      body,
      background: '#FFFFFF',
      layout: body ? 'title-content' : 'title-only',
    });
    return slides;
  }

  if (preamble.length) {
    const text = plainBlock(preamble);
    if (text) {
      slides.push({
        id: createSlideId(),
        title: text.split('\n')[0].slice(0, 90),
        body: text.split('\n').slice(1).join('\n').trim(),
        background: '#FFFFFF',
        layout: 'title-content',
      });
    }
  }

  for (const section of sections) {
    if (slides.length >= MAX_GENERATED_SLIDES) {
      break;
    }
    const body = plainBlock(section.body);
    slides.push({
      id: createSlideId(),
      title: section.title || 'Untitled',
      body,
      background: '#FFFFFF',
      layout: body ? 'title-content' : 'title-only',
    });
  }

  return slides;
}
