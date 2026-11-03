import type { Cell, CellWithRowAndCol, Sheet } from '@fortune-sheet/core';
import type { JSONContent } from '@tiptap/core';
import type { SlideData, SlideLayout } from '../types';
import { createSlide } from './converters';
import { parseCsvText } from './markdownParser';

/**
 * Import of files that were produced outside the app (for example by an AI
 * chat): Excel workbooks, Word documents and PowerPoint decks.
 *
 * Everything runs locally in the renderer.  AI answers are never fetched from
 * a network API here; the bytes come from a dropped file or from the download
 * folder that the Python side fills.
 */

export type ImportKind = 'spreadsheet' | 'document' | 'slides';

const SPREADSHEET_EXTENSIONS = ['xlsx', 'xls', 'csv', 'tsv'];

/** Guard rails so a huge workbook cannot freeze the renderer. */
export const MAX_IMPORT_BYTES = 20 * 1024 * 1024;
const MAX_PARAGRAPHS = 4000;
const MAX_SLIDE_LINES = 60;

const WORD_NS = 'http://schemas.openxmlformats.org/wordprocessingml/2006/main';
const PRESENTATION_NS = 'http://schemas.openxmlformats.org/presentationml/2006/main';
const DRAWING_NS = 'http://schemas.openxmlformats.org/drawingml/2006/main';

export function supportedImportNames(): string {
  return '.xlsx / .xls / .csv / .tsv / .docx / .pptx';
}

export function importKindForName(name: string): ImportKind | null {
  const extension = extensionOf(name);
  if (SPREADSHEET_EXTENSIONS.includes(extension)) {
    return 'spreadsheet';
  }
  if (extension === 'docx') {
    return 'document';
  }
  if (extension === 'pptx') {
    return 'slides';
  }
  return null;
}

/** Decode the base64 payload the Python side sends through the QWebChannel. */
export function decodeBase64(base64: string): ArrayBuffer {
  const binary = atob(String(base64 ?? ''));
  const bytes = new Uint8Array(binary.length);
  for (let index = 0; index < binary.length; index += 1) {
    bytes[index] = binary.charCodeAt(index);
  }
  return bytes.buffer;
}

/** Rename imported sheets that would collide with sheets already in the book. */
export function withUniqueNames(sheets: Sheet[], existing: string[]): Sheet[] {
  const used = new Set(existing.map((name) => String(name ?? '').trim()));
  return sheets.map((sheet) => {
    const original = String(sheet.name ?? '').trim() || 'Imported';
    let name = original;
    let suffix = 2;
    while (used.has(name)) {
      name = `${original} (${suffix})`;
      suffix += 1;
    }
    used.add(name);
    return { ...sheet, name };
  });
}

/* ------------------------------------------------------------------ */
/* Helpers                                                             */
/* ------------------------------------------------------------------ */

function extensionOf(name: string): string {
  const match = /\.([a-z0-9]+)$/i.exec(String(name ?? '').trim());
  return match ? match[1].toLowerCase() : '';
}

function baseName(name: string): string {
  const file = String(name ?? '').replace(/^.*[\\/]/, '');
  return file.replace(/\.[a-z0-9]+$/i, '') || 'Imported';
}

function createSheetId(order: number): string {
  return `sheet-${Date.now().toString(36)}-${order}-${Math.random().toString(36).slice(2, 8)}`;
}

function toCell(value: unknown): Cell | null {
  if (value === null || value === undefined) {
    return null;
  }
  if (value instanceof Date) {
    const text = formatDate(value);
    return { v: text, m: text };
  }
  if (typeof value === 'number') {
    return Number.isFinite(value) ? { v: value, m: String(value) } : null;
  }
  if (typeof value === 'boolean') {
    return { v: value, m: value ? 'TRUE' : 'FALSE' };
  }
  const text = String(value);
  return text.trim() ? { v: text, m: text } : null;
}

function formatDate(value: Date): string {
  const pad = (part: number) => String(part).padStart(2, '0');
  const date = `${value.getFullYear()}-${pad(value.getMonth() + 1)}-${pad(value.getDate())}`;
  if (value.getHours() || value.getMinutes() || value.getSeconds()) {
    return `${date} ${pad(value.getHours())}:${pad(value.getMinutes())}`;
  }
  return date;
}

function sheetFromMatrix(
  name: string,
  matrix: (Cell | null)[][],
  order: number,
  config?: Sheet['config'],
): Sheet {
  const width = matrix.reduce((max, row) => Math.max(max, row.length), 0);
  const celldata: CellWithRowAndCol[] = [];
  matrix.forEach((row, r) => {
    row.forEach((cell, c) => {
      if (cell) {
        celldata.push({ r, c, v: cell });
      }
    });
  });
  return {
    name: (name.trim() || `Sheet${order + 1}`).slice(0, 80),
    id: createSheetId(order),
    order,
    row: Math.max(matrix.length + 20, 36),
    column: Math.max(width + 2, 10),
    celldata,
    ...(config ? { config } : {}),
  };
}

/* ------------------------------------------------------------------ */
/* Spreadsheets (Excel / CSV)                                          */
/* ------------------------------------------------------------------ */

interface SheetJsWorksheet {
  [key: string]: unknown;
}

interface SheetJsWorkbook {
  SheetNames: string[];
  Sheets: Record<string, SheetJsWorksheet | undefined>;
}

interface SheetJsApi {
  read(data: ArrayBuffer, options: { type: 'array'; cellDates?: boolean }): SheetJsWorkbook;
  utils: {
    sheet_to_json(
      sheet: SheetJsWorksheet,
      options: { header: 1; raw?: boolean; defval?: unknown; blankrows?: boolean },
    ): unknown[][];
  };
}

interface XlsxMerge {
  s?: { r?: number; c?: number };
  e?: { r?: number; c?: number };
}

interface XlsxColumn {
  wch?: number;
  wpx?: number;
}

/**
 * Keep merged cells and column widths so an imported sheet still looks like
 * the original file instead of collapsing everything into column A.
 */
function xlsxSheetConfig(worksheet: SheetJsWorksheet): Sheet['config'] | undefined {
  const config: NonNullable<Sheet['config']> = {};

  const merges = worksheet['!merges'];
  if (Array.isArray(merges)) {
    const merge: NonNullable<NonNullable<Sheet['config']>['merge']> = {};
    for (const item of merges as XlsxMerge[]) {
      const startRow = Number(item?.s?.r ?? 0);
      const startColumn = Number(item?.s?.c ?? 0);
      const endRow = Number(item?.e?.r ?? startRow);
      const endColumn = Number(item?.e?.c ?? startColumn);
      const rs = endRow - startRow + 1;
      const cs = endColumn - startColumn + 1;
      if (rs < 1 || cs < 1 || (rs === 1 && cs === 1)) {
        continue;
      }
      merge[`${startRow}_${startColumn}`] = {
        r: startRow,
        c: startColumn,
        rs,
        cs,
      };
    }
    if (Object.keys(merge).length) {
      config.merge = merge;
    }
  }

  const columns = worksheet['!cols'];
  if (Array.isArray(columns)) {
    const columnlen: Record<string, number> = {};
    (columns as (XlsxColumn | null | undefined)[]).forEach((column, index) => {
      if (!column) {
        return;
      }
      const width = column.wpx ?? (column.wch ? Math.round(column.wch * 7 + 5) : undefined);
      if (!width || !Number.isFinite(width) || width <= 0) {
        return;
      }
      columnlen[String(index)] = Math.min(Math.max(Math.round(width), 30), 600);
    });
    if (Object.keys(columnlen).length) {
      config.columnlen = columnlen;
    }
  }

  return Object.keys(config).length ? config : undefined;
}

async function loadSheetJs(): Promise<SheetJsApi> {
  // Imported lazily so the editor still starts when only a small part of the
  // feature is used, and so a missing dependency surfaces as a message.
  const module = await import('xlsx');
  const api =
    (module as unknown as { default?: SheetJsApi }).default ??
    (module as unknown as SheetJsApi);
  if (!api || typeof api.read !== 'function') {
    throw new Error('Excel 読み込みライブラリを初期化できませんでした。');
  }
  return api;
}

/** Read an .xlsx / .xls / .csv / .tsv file into FortuneSheet sheets. */
export async function readSpreadsheet(name: string, buffer: ArrayBuffer): Promise<Sheet[]> {
  const extension = extensionOf(name);

  if (extension === 'csv' || extension === 'tsv') {
    const text = new TextDecoder('utf-8').decode(new Uint8Array(buffer));
    const rows =
      extension === 'tsv'
        ? text
            .replace(/\r\n?/g, '\n')
            .split('\n')
            .map((line) => line.split('\t').map((cell) => cell.trim()))
            .filter((row) => row.some((cell) => cell !== ''))
        : parseCsvText(text);
    if (!rows.length) {
      return [];
    }
    return [sheetFromMatrix(baseName(name), rows.map((row) => row.map((cell) => toCell(cell))), 0)];
  }

  const xlsx = await loadSheetJs();
  const workbook = xlsx.read(buffer, { type: 'array', cellDates: true });
  const sheets: Sheet[] = [];

  for (let index = 0; index < workbook.SheetNames.length; index += 1) {
    const sheetName = workbook.SheetNames[index];
    const worksheet = workbook.Sheets[sheetName];
    if (!worksheet) {
      continue;
    }
    let matrix: unknown[][] = [];
    try {
      matrix = xlsx.utils.sheet_to_json(worksheet, {
        header: 1,
        raw: true,
        defval: null,
        blankrows: false,
      });
    } catch (error) {
      console.warn('[fileImport] シートを読み取れませんでした', error);
      continue;
    }
    const rows = matrix
      .filter((row) => Array.isArray(row))
      .map((row) => row.map((cell) => toCell(cell)));
    if (!rows.some((row) => row.some((cell) => cell !== null))) {
      continue;
    }
    sheets.push(
      sheetFromMatrix(
        sheetName || baseName(name),
        rows,
        index,
        xlsxSheetConfig(worksheet),
      ),
    );
  }

  return sheets;
}

/* ------------------------------------------------------------------ */
/* ZIP containers (docx / pptx)                                        */
/* ------------------------------------------------------------------ */

interface ZipEntry {
  async(type: 'string'): Promise<string>;
}

interface ZipBundle {
  file(path: string): ZipEntry | null;
  files: Record<string, unknown>;
}

interface ZipFactory {
  loadAsync(data: ArrayBuffer): Promise<ZipBundle>;
}

async function loadZip(buffer: ArrayBuffer): Promise<ZipBundle> {
  const module = await import('jszip');
  const factory =
    (module as unknown as { default?: ZipFactory }).default ??
    (module as unknown as ZipFactory);
  if (!factory || typeof factory.loadAsync !== 'function') {
    throw new Error('ZIP 読み込みライブラリを初期化できませんでした。');
  }
  return factory.loadAsync(buffer);
}

function parseXml(xml: string): Document | null {
  const document = new DOMParser().parseFromString(xml, 'application/xml');
  return document.getElementsByTagName('parsererror').length ? null : document;
}

/* ------------------------------------------------------------------ */
/* Word (.docx)                                                        */
/* ------------------------------------------------------------------ */

const HEADING_STYLE_RE = /^heading\s*([1-6])$/i;

/** Read a .docx file into the Tiptap nodes used by the Word editor. */
export async function readDocument(name: string, buffer: ArrayBuffer): Promise<JSONContent[]> {
  const zip = await loadZip(buffer);
  const entry = zip.file('word/document.xml');
  if (!entry) {
    throw new Error(`${baseName(name)} は本文（word/document.xml）を含む Word ファイルではありません。`);
  }
  const document = parseXml(await entry.async('string'));
  if (!document) {
    throw new Error(`${baseName(name)} の文書構造を解析できませんでした。`);
  }

  const paragraphs = document.getElementsByTagNameNS(WORD_NS, 'p');
  const nodes: JSONContent[] = [];
  let bullets: JSONContent[] = [];

  const flushBullets = () => {
    if (bullets.length) {
      nodes.push({ type: 'bulletList', content: bullets });
      bullets = [];
    }
  };

  for (let index = 0; index < paragraphs.length; index += 1) {
    if (nodes.length >= MAX_PARAGRAPHS) {
      break;
    }
    const paragraph = paragraphs[index];
    const text = readWordParagraphText(paragraph);
    const isList = paragraph.getElementsByTagNameNS(WORD_NS, 'numPr').length > 0;
    const level = readWordHeadingLevel(paragraph);

    if (isList && text) {
      bullets.push({
        type: 'listItem',
        content: [{ type: 'paragraph', content: [{ type: 'text', text }] }],
      });
      continue;
    }

    flushBullets();
    if (!text) {
      continue;
    }
    if (level) {
      nodes.push({
        type: 'heading',
        attrs: { level },
        content: [{ type: 'text', text }],
      });
    } else {
      nodes.push({ type: 'paragraph', content: [{ type: 'text', text }] });
    }
  }

  flushBullets();
  return nodes;
}

function readWordParagraphText(paragraph: Element): string {
  let text = '';

  const walk = (node: Node) => {
    if (node.nodeType !== Node.ELEMENT_NODE) {
      return;
    }
    const element = node as Element;
    const local = element.localName;
    if (local === 't') {
      text += element.textContent ?? '';
      return;
    }
    if (local === 'tab') {
      text += '\t';
      return;
    }
    if (local === 'br' || local === 'cr') {
      text += '\n';
      return;
    }
    // Field codes and deleted revisions are not part of the visible text.
    if (local === 'instrText' || local === 'delText') {
      return;
    }
    for (let index = 0; index < element.childNodes.length; index += 1) {
      walk(element.childNodes[index]);
    }
  };

  walk(paragraph);
  return text.replace(/[ \t]+$/g, '');
}

function readWordHeadingLevel(paragraph: Element): number {
  const style = paragraph.getElementsByTagNameNS(WORD_NS, 'pStyle')[0];
  if (!style) {
    return 0;
  }
  const value = String(
    style.getAttributeNS(WORD_NS, 'val') ?? style.getAttribute('w:val') ?? '',
  ).trim();
  const match = HEADING_STYLE_RE.exec(value);
  if (match) {
    return Number(match[1]);
  }
  return /^title$/i.test(value) ? 1 : 0;
}

/* ------------------------------------------------------------------ */
/* PowerPoint (.pptx)                                                  */
/* ------------------------------------------------------------------ */

/** Read a .pptx file into the slides used by the slide editor. */
export async function readPresentation(name: string, buffer: ArrayBuffer): Promise<SlideData[]> {
  const zip = await loadZip(buffer);
  const paths = await orderedSlidePaths(zip);
  if (!paths.length) {
    throw new Error(`${baseName(name)} にスライドが見つかりませんでした。`);
  }

  const slides: SlideData[] = [];
  for (const path of paths) {
    const entry = zip.file(path);
    if (!entry) {
      continue;
    }
    const document = parseXml(await entry.async('string'));
    if (!document) {
      continue;
    }
    slides.push(slideFromXml(document));
  }
  return slides;
}

async function orderedSlidePaths(zip: ZipBundle): Promise<string[]> {
  const numeric = Object.keys(zip.files)
    .filter((path) => /^ppt\/slides\/slide\d+\.xml$/.test(path))
    .sort((left, right) => slideNumber(left) - slideNumber(right));

  try {
    const presentation = zip.file('ppt/presentation.xml');
    const relationships = zip.file('ppt/_rels/presentation.xml.rels');
    if (!presentation || !relationships) {
      return numeric;
    }
    const presentationXml = await presentation.async('string');
    const relationshipXml = await relationships.async('string');

    const targets = new Map<string, string>();
    for (const tag of relationshipXml.match(/<Relationship\b[^>]*>/g) ?? []) {
      const id = /Id="([^"]+)"/.exec(tag)?.[1];
      const target = /Target="([^"]+)"/.exec(tag)?.[1];
      if (!id || !target) {
        continue;
      }
      const path = target.startsWith('/')
        ? target.slice(1)
        : `ppt/${target.replace(/^\.\//, '')}`;
      targets.set(id, path);
    }

    const ordered: string[] = [];
    for (const tag of presentationXml.match(/<p:sldId\b[^>]*>/g) ?? []) {
      const id = /r:id="([^"]+)"/.exec(tag)?.[1];
      const path = id ? targets.get(id) : undefined;
      if (path && zip.file(path)) {
        ordered.push(path);
      }
    }
    return ordered.length ? ordered : numeric;
  } catch (error) {
    console.warn('[fileImport] スライド順序を取得できませんでした', error);
    return numeric;
  }
}

function slideNumber(path: string): number {
  const match = /slide(\d+)\.xml$/.exec(path);
  return match ? Number(match[1]) : 0;
}

function slideFromXml(document: Document): SlideData {
  let title = '';
  const bodyLines: string[] = [];
  const shapes = document.getElementsByTagNameNS(PRESENTATION_NS, 'sp');

  for (let index = 0; index < shapes.length; index += 1) {
    const shape = shapes[index];
    const lines = readShapeLines(shape);
    if (!lines.length) {
      continue;
    }
    const placeholder = shape.getElementsByTagNameNS(PRESENTATION_NS, 'ph')[0];
    const type = String(placeholder?.getAttribute('type') ?? 'body');
    // Slide numbers, dates and footers would only add noise to the body text.
    if (type === 'sldNum' || type === 'dt' || type === 'ftr') {
      continue;
    }
    if (!title && (type === 'title' || type === 'ctrTitle')) {
      title = lines.join(' ').slice(0, 200);
      continue;
    }
    for (const line of lines) {
      if (bodyLines.length >= MAX_SLIDE_LINES) {
        break;
      }
      bodyLines.push(line);
    }
  }

  if (!title && bodyLines.length) {
    title = bodyLines.shift() ?? '';
  }

  const body = bodyLines.join('\n');
  const layout: SlideLayout = body ? 'title-content' : title ? 'title-only' : 'blank';
  return createSlide({
    title: title || 'Untitled',
    body,
    background: readBackground(document),
    layout,
  });
}

function readShapeLines(shape: Element): string[] {
  const lines: string[] = [];
  const paragraphs = shape.getElementsByTagNameNS(DRAWING_NS, 'p');
  for (let index = 0; index < paragraphs.length; index += 1) {
    const runs = paragraphs[index].getElementsByTagNameNS(DRAWING_NS, 't');
    let text = '';
    for (let run = 0; run < runs.length; run += 1) {
      text += runs[run].textContent ?? '';
    }
    const trimmed = text.trim();
    if (trimmed) {
      lines.push(trimmed);
    }
  }
  return lines;
}

function readBackground(document: Document): string {
  const background = document.getElementsByTagNameNS(PRESENTATION_NS, 'bg')[0];
  if (!background) {
    return '#FFFFFF';
  }
  const colors = background.getElementsByTagNameNS(DRAWING_NS, 'srgbClr');
  for (let index = 0; index < colors.length; index += 1) {
    const value = String(colors[index].getAttribute('val') ?? '').trim();
    if (/^[0-9a-fA-F]{6}$/.test(value)) {
      return `#${value.toUpperCase()}`;
    }
  }
  return '#FFFFFF';
}
