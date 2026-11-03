import type { JSONContent } from '@tiptap/core';
import {
  EMPTY_DOCUMENT,
  type ProjectData,
  type SlideData,
  type SlideElement,
  type SlideLayout,
} from '../types';

export const DEFAULT_SLIDE_BACKGROUND = '#FFFFFF';

let slideCounter = 0;
let elementCounter = 0;

/** Generate an id that never collides with one created earlier in the session. */
export function createSlideId(): string {
  slideCounter += 1;
  return `slide-${Date.now().toString(36)}-${slideCounter.toString(36)}`;
}

export function createSlideElementId(): string {
  elementCounter += 1;
  return `element-${Date.now().toString(36)}-${elementCounter.toString(36)}`;
}

export const SLIDE_LAYOUTS: SlideLayout[] = ['title-content', 'title-only', 'section', 'blank'];

export const LAYOUT_LABELS: Record<SlideLayout, string> = {
  'title-content': 'タイトル + 本文',
  'title-only': 'タイトルのみ',
  section: 'セクション区切り',
  blank: '空白',
};

export function createSlide(partial: Partial<SlideData> = {}): SlideData {
  const layout = partial.layout && SLIDE_LAYOUTS.includes(partial.layout) ? partial.layout : 'title-content';
  return {
    id: partial.id && partial.id.trim() ? partial.id : createSlideId(),
    title: typeof partial.title === 'string' ? partial.title : 'New Slide',
    body: typeof partial.body === 'string' ? partial.body : '',
    background:
      typeof partial.background === 'string' && partial.background.trim()
        ? partial.background
        : DEFAULT_SLIDE_BACKGROUND,
    layout,
    elements: ensureSlideElements(partial.elements),
  };
}

export function ensureSlideElements(raw: unknown): SlideElement[] {
  if (!Array.isArray(raw)) {
    return [];
  }
  return raw.flatMap((item) => {
    if (!item || typeof item !== 'object') {
      return [];
    }
    const candidate = item as Partial<SlideElement>;
    const kind = candidate.kind === 'shape' ? 'shape' : 'text';
    const text = typeof candidate.text === 'string' ? candidate.text : '';
    const number = (value: unknown, fallback: number) =>
      typeof value === 'number' && Number.isFinite(value) ? Math.min(Math.max(value, 0), 100) : fallback;
    return [{
      id:
        typeof candidate.id === 'string' && candidate.id.trim()
          ? candidate.id.trim()
          : createSlideElementId(),
      kind,
      text,
      x: number(candidate.x, 10),
      y: number(candidate.y, 10),
      width: number(candidate.width, 30),
      height: number(candidate.height, 12),
      color: typeof candidate.color === 'string' && candidate.color ? candidate.color : '#1A1D22',
      background:
        typeof candidate.background === 'string' && candidate.background
          ? candidate.background
          : kind === 'shape'
            ? '#DCE6F8'
            : undefined,
    }];
  });
}

/** One paragraph per line; never interprets the text as HTML. */
export function textToParagraphNodes(text: string): JSONContent[] {
  const lines = String(text ?? '')
    .replace(/\r\n?/g, '\n')
    .split('\n');
  const nodes: JSONContent[] = [];
  for (const line of lines) {
    const trimmed = line.trim();
    if (!trimmed) {
      continue;
    }
    nodes.push({ type: 'paragraph', content: [{ type: 'text', text: trimmed }] });
  }
  return nodes;
}

export function textToDocument(text: string): JSONContent {
  const content = textToParagraphNodes(text);
  return content.length ? { type: 'doc', content } : EMPTY_DOCUMENT;
}

function isTiptapNode(value: unknown): boolean {
  if (!value || typeof value !== 'object') {
    return false;
  }
  const node = value as { type?: unknown; content?: unknown };
  if (typeof node.type !== 'string' || node.type.length === 0) {
    return false;
  }
  if (node.content === undefined) {
    return true;
  }
  if (!Array.isArray(node.content)) {
    return false;
  }
  return node.content.every((child) => isTiptapNode(child));
}

/** Accept only data that looks like a Tiptap document. */
export function ensureDocument(raw: unknown): JSONContent | null {
  if (!raw || typeof raw !== 'object') {
    return null;
  }
  const document = raw as JSONContent;
  if (document.type !== 'doc' || !Array.isArray(document.content)) {
    return null;
  }
  if (!document.content.every((child) => isTiptapNode(child))) {
    return null;
  }
  return document;
}

/** Validate slide data coming from a file or from Python. */
export function ensureSlides(raw: unknown): SlideData[] {
  if (!Array.isArray(raw)) {
    return [];
  }
  const seen = new Set<string>();
  const slides: SlideData[] = [];
  for (const item of raw) {
    if (!item || typeof item !== 'object') {
      continue;
    }
    const candidate = item as Partial<SlideData>;
    let id = typeof candidate.id === 'string' && candidate.id.trim() ? candidate.id.trim() : createSlideId();
    if (seen.has(id)) {
      id = createSlideId();
    }
    seen.add(id);
    slides.push(createSlide({ ...candidate, id }));
  }
  return slides;
}

export function ensureProject(raw: unknown): ProjectData {
  const source = (raw && typeof raw === 'object' ? raw : {}) as Partial<ProjectData>;
  const activeMode =
    source.activeMode === 'document' || source.activeMode === 'slides' || source.activeMode === 'spreadsheet'
      ? source.activeMode
      : 'spreadsheet';
  const sheets =
    source.spreadsheet && Array.isArray(source.spreadsheet.sheets) ? source.spreadsheet.sheets : [];
  return {
    format: 'ai-office-workspace',
    version: 1,
    activeMode,
    spreadsheet: { sheets },
    document: ensureDocument(source.document),
    slides: ensureSlides(source.slides),
  };
}

/** Pick a readable text colour for a slide background. */
export function contrastingText(background: string): string {
  const value = String(background ?? '').trim();
  let hex = value.startsWith('#') ? value.slice(1) : value;
  if (hex.length === 3) {
    hex = hex
      .split('')
      .map((character) => character + character)
      .join('');
  }
  if (!/^[0-9a-fA-F]{6}$/.test(hex)) {
    return '#1A1D22';
  }
  const red = parseInt(hex.slice(0, 2), 16);
  const green = parseInt(hex.slice(2, 4), 16);
  const blue = parseInt(hex.slice(4, 6), 16);
  const luminance = (0.299 * red + 0.587 * green + 0.114 * blue) / 255;
  return luminance > 0.6 ? '#1A1D22' : '#F7F8FA';
}

export function truncate(value: string, limit = 80): string {
  const text = String(value ?? '');
  return text.length > limit ? `${text.slice(0, limit - 1)}…` : text;
}

export const SLIDE_BACKGROUNDS = ['#FFFFFF', '#F3F5F9', '#0F172A', '#1D4ED8', '#0F766E', '#7C2D12', '#4C1D95', '#111318'];
