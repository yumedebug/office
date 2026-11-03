import type { JSONContent } from '@tiptap/core';
import type { Editor } from '@tiptap/react';
import type { Sheet } from '@fortune-sheet/core';
import type { WorkbookInstance } from '@fortune-sheet/react';

export type Mode = 'spreadsheet' | 'document' | 'slides';

export const MODES: Mode[] = ['spreadsheet', 'document', 'slides'];

export const MODE_LABELS: Record<Mode, string> = {
  spreadsheet: 'Excel',
  document: 'Word',
  slides: 'Slide',
};

export type SlideLayout = 'title-content' | 'title-only' | 'section' | 'blank';

export type SlideElementKind = 'text' | 'shape';

export interface SlideElement {
  id: string;
  kind: SlideElementKind;
  text: string;
  x: number;
  y: number;
  width: number;
  height: number;
  color: string;
  background?: string;
}

export interface SlideData {
  id: string;
  title: string;
  body: string;
  background: string;
  layout: SlideLayout;
  elements?: SlideElement[];
}

export interface ProjectData {
  format: 'ai-office-workspace';
  version: 1;
  activeMode: Mode;
  spreadsheet: { sheets: Sheet[] };
  document: JSONContent | null;
  slides: SlideData[];
  metadata?: { title?: string; updatedAt?: string };
}

export interface OperationResult {
  ok: boolean;
  message?: string;
  error?: string;
  needsConfirm?: boolean;
  count?: number;
  rows?: number;
  columns?: number;
}

export type AiAction = 'text' | 'table' | 'document' | 'slides';

export interface SingleRange {
  row: [number, number];
  column: [number, number];
}

/** Imperative surface exposed by the FortuneSheet based editor. */
export interface SpreadsheetHandle {
  getWorkbook(): WorkbookInstance | null;
  /** Replace the workbook contents and optionally activate one sheet. */
  setSheets(sheets: Sheet[], activeSheetId?: string): void;
  /** Activate a sheet tab, scrolling it into view. */
  activateSheet(sheetId: string): void;
}

/** Imperative surface exposed by the Tiptap based editor. */
export interface DocumentHandle {
  getEditor(): Editor | null;
  setContent(content: JSONContent | null): void;
}

/** Imperative surface exposed by the Reveal.js backed slide editor. */
export interface PresentationHandle {
  getSlides(): SlideData[];
  setSlides(slides: SlideData[]): void;
  getActiveIndex(): number;
  setActiveIndex(index: number): void;
}

/**
 * The API that Python calls through runJavaScript().  Every method that may
 * fail returns a JSON string with an ``OperationResult`` body so the Python
 * side can report the outcome without guessing.
 */
export interface OfficeEditorApi {
  insertText(text: string): string;
  getContent(): string;
  getAllContent(): string;
  setContent(data: unknown): string;
  setMode(mode: string): string;
  getMode(): string;
  isReady(): boolean;
  planAiResponse(text: string, action: string): string;
  applyAiResponse(text: string, action: string, confirmed: boolean): string;
  /** Import an .xlsx / .csv / .docx / .pptx file sent as base64 by Python. */
  importFile(fileName: string, base64: string): string;
}

export const EMPTY_DOCUMENT: JSONContent = {
  type: 'doc',
  content: [{ type: 'paragraph' }],
};

export function isMode(value: unknown): value is Mode {
  return value === 'spreadsheet' || value === 'document' || value === 'slides';
}

declare global {
  interface Window {
    QWebChannel?: unknown;
    qt?: { webChannelTransport?: unknown };
    officeEditor?: OfficeEditorApi;
  }
}
