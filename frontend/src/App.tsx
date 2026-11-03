import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import type { Sheet } from '@fortune-sheet/core';
import SpreadsheetEditor from './components/SpreadsheetEditor';
import DocumentEditor from './components/DocumentEditor';
import PresentationEditor from './components/PresentationEditor';
import GoogleEmbedPanel from './components/GoogleEmbedPanel';
import { createSpreadsheetAdapter } from './adapters/spreadsheetAdapter';
import { createDocumentAdapter } from './adapters/documentAdapter';
import { createPresentationAdapter } from './adapters/presentationAdapter';
import {
  connectBridge,
  installOfficeApi,
  notifyContentChanged,
  notifyError,
  notifyModeChanged,
  notifyReady,
  notifySaveRequest,
  notifyStatus,
  suppressContentNotifications,
} from './bridge/officeBridge';
import { ensureProject } from './utils/converters';
import {
  MAX_IMPORT_BYTES,
  decodeBase64,
  importKindForName,
  readDocument,
  readPresentation,
  readSpreadsheet,
  supportedImportNames,
  withUniqueNames,
} from './utils/fileImport';
import { markdownToSlides, parseTable } from './utils/markdownParser';
import {
  MODES,
  MODE_LABELS,
  isMode,
  type DocumentHandle,
  type Mode,
  type OfficeEditorApi,
  type OperationResult,
  type PresentationHandle,
  type ProjectData,
  type SpreadsheetHandle,
} from './types';

type BridgeState = 'connecting' | 'connected' | 'standalone';

export default function App() {
  const [mode, setMode] = useState<Mode>('spreadsheet');
  const [bridgeState, setBridgeState] = useState<BridgeState>('connecting');
  const [dragActive, setDragActive] = useState(false);
  const [googlePanelOpen, setGooglePanelOpen] = useState(false);

  const modeRef = useRef<Mode>('spreadsheet');
  const readyRef = useRef(false);

  const spreadsheetRef = useRef<SpreadsheetHandle>(null);
  /**
   * Sheets accumulated while several files are imported in one go.
   * ``spreadsheetAdapter.getData()`` still reports the pre-remount workbook,
   * so a drop of two spreadsheets would otherwise lose the first one.
   */
  const importSheetsRef = useRef<Sheet[] | null>(null);
  const documentRef = useRef<DocumentHandle>(null);
  const presentationRef = useRef<PresentationHandle>(null);

  const spreadsheetAdapter = useMemo(
    () => createSpreadsheetAdapter(() => spreadsheetRef.current),
    [],
  );
  const documentAdapter = useMemo(() => createDocumentAdapter(() => documentRef.current), []);
  const presentationAdapter = useMemo(
    () => createPresentationAdapter(() => presentationRef.current),
    [],
  );

  useEffect(() => {
    readyRef.current = true;
  }, []);

  // Ctrl+S inside the editor asks the Qt side to save through the channel; the
  // Qt side ignores duplicate requests while a save is already running.
  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 's') {
        event.preventDefault();
        notifySaveRequest();
      }
    };
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, []);

  /* ---------------------------------------------------------------- */
  /* Bridge                                                            */
  /* ---------------------------------------------------------------- */

  useEffect(() => {
    let cancelled = false;
    void connectBridge().then((connected) => {
      if (cancelled) {
        return;
      }
      setBridgeState(connected ? 'connected' : 'standalone');
      if (connected) {
        notifyReady();
        notifyModeChanged(modeRef.current);
        notifyStatus('Ready');
      }
    });
    return () => {
      cancelled = true;
    };
  }, []);

  /* ---------------------------------------------------------------- */
  /* Mode handling                                                     */
  /* ---------------------------------------------------------------- */

  const applyMode = useCallback((next: Mode, notify = true) => {
    modeRef.current = next;
    setMode(next);
    if (notify) {
      notifyModeChanged(next);
    }
  }, []);

  /* ---------------------------------------------------------------- */
  /* Data access                                                       */
  /* ---------------------------------------------------------------- */

  const contentForMode = useCallback(
    (target: Mode): unknown => {
      switch (target) {
        case 'spreadsheet':
          return { sheets: spreadsheetAdapter.getData() ?? [] };
        case 'document':
          return documentAdapter.getData();
        default:
          return presentationAdapter.getData();
      }
    },
    [documentAdapter, presentationAdapter, spreadsheetAdapter],
  );

  const buildProject = useCallback(
    (): ProjectData => ({
      format: 'ai-office-workspace',
      version: 1,
      activeMode: modeRef.current,
      spreadsheet: { sheets: spreadsheetAdapter.getData() ?? [] },
      document: documentAdapter.getData(),
      slides: presentationAdapter.getData(),
    }),
    [documentAdapter, presentationAdapter, spreadsheetAdapter],
  );

  const applyProject = useCallback(
    (raw: unknown): OperationResult => {
      try {
        const data = typeof raw === 'string' ? JSON.parse(raw) : raw;
        const project = ensureProject(data);
        // The workbook is remounted with new data; do not report that as an edit.
        suppressContentNotifications();
        spreadsheetAdapter.setData(project.spreadsheet.sheets.length ? project.spreadsheet.sheets : null);
        documentAdapter.setData(project.document);
        presentationAdapter.setData(project.slides);
        applyMode(project.activeMode, false);
        return { ok: true, message: 'プロジェクトを復元しました' };
      } catch (error) {
        return {
          ok: false,
          error: error instanceof Error ? error.message : String(error),
        };
      }
    },
    [applyMode, documentAdapter, presentationAdapter, spreadsheetAdapter],
  );

  /* ---------------------------------------------------------------- */
  /* File import (Excel / Word / Slide)                                */
  /* ---------------------------------------------------------------- */

  const importBuffer = useCallback(
    async (fileName: string, buffer: ArrayBuffer): Promise<OperationResult> => {
      const kind = importKindForName(fileName);
      if (!kind) {
        return {
          ok: false,
          error: `対応していない形式です（${supportedImportNames()}）: ${fileName}`,
        };
      }

      try {
        if (kind === 'spreadsheet') {
          const imported = await readSpreadsheet(fileName, buffer);
          if (!imported.length) {
            return { ok: false, error: `${fileName} からシートを読み取れませんでした。` };
          }
          const existing = importSheetsRef.current ?? spreadsheetAdapter.getData() ?? [];
          const sheets = withUniqueNames(
            imported,
            existing.map((sheet) => sheet.name),
          );
          // FortuneSheet keeps the tab order in ``order``: continue the existing
          // sequence so the imported sheets land after the current ones.
          const combined = [...existing, ...sheets].map((sheet, index) => ({
            ...sheet,
            order: index,
            // FortuneSheet marks the sheet to show with ``status: 1``.
            status: sheet.id === sheets[0]?.id ? 1 : 0,
          }));
          importSheetsRef.current = combined;
          // Activate the first imported sheet once the workbook is remounted,
          // so the file the user just dropped/opened is what they see.
          spreadsheetAdapter.setData(combined, sheets[0]?.id);
          applyMode('spreadsheet');
          notifyContentChanged();
          return {
            ok: true,
            message: `${fileName}: ${sheets.length} 枚のシートを追加し、${sheets[0]?.name ?? 'シート'} を開きました`,
          };
        }

        if (kind === 'document') {
          const nodes = await readDocument(fileName, buffer);
          if (!nodes.length) {
            return { ok: false, error: `${fileName} から本文を読み取れませんでした。` };
          }
          documentAdapter.appendNodes(nodes);
          applyMode('document');
          notifyContentChanged();
          return { ok: true, message: `${fileName} を Word 文書の末尾に追加しました` };
        }

        const slides = await readPresentation(fileName, buffer);
        if (!slides.length) {
          return { ok: false, error: `${fileName} からスライドを読み取れませんでした。` };
        }
        applyMode('slides');
        const result = presentationAdapter.appendSlides(slides);
        if (result.ok) {
          notifyContentChanged();
        }
        return result;
      } catch (error) {
        return {
          ok: false,
          error: error instanceof Error ? error.message : String(error),
        };
      }
    },
    [applyMode, documentAdapter, presentationAdapter, spreadsheetAdapter],
  );

  const runImport = useCallback(
    async (fileName: string, buffer: ArrayBuffer): Promise<OperationResult> => {
      const result = await importBuffer(fileName, buffer);
      if (result.ok) {
        notifyStatus(result.message ?? `${fileName} を読み込みました`);
      } else {
        notifyError(result.error ?? `${fileName} を読み込めませんでした。`);
      }
      return result;
    },
    [importBuffer],
  );

  const handleDroppedFiles = useCallback(
    async (files: File[]) => {
      // Start from the live workbook; the accumulator only serves this batch.
      importSheetsRef.current = null;
      try {
        for (const file of files) {
          if (!importKindForName(file.name)) {
            notifyError(`対応していない形式です（${supportedImportNames()}）: ${file.name}`);
            continue;
          }
          if (file.size > MAX_IMPORT_BYTES) {
            notifyError(
              `${file.name} は大きすぎます（${Math.round(MAX_IMPORT_BYTES / (1024 * 1024))} MB まで取り込めます）`,
            );
            continue;
          }
          try {
            const buffer = await file.arrayBuffer();
            await runImport(file.name, buffer);
          } catch (error) {
            notifyError(
              `${file.name} を読み込めませんでした: ${error instanceof Error ? error.message : String(error)}`,
            );
          }
        }
      } finally {
        importSheetsRef.current = null;
      }
    },
    [runImport],
  );

  const importBase64 = useCallback(
    (fileName: string, base64: string) => {
      if (!importKindForName(fileName)) {
        notifyError(`対応していない形式です（${supportedImportNames()}）: ${fileName}`);
        return;
      }
      // Do not block the runJavaScript() reply: the outcome is reported through
      // the bridge so the status bar shows it.
      importSheetsRef.current = null;
      void (async () => {
        try {
          await runImport(fileName, decodeBase64(base64));
        } catch (error) {
          notifyError(
            `${fileName} を読み込めませんでした: ${error instanceof Error ? error.message : String(error)}`,
          );
        } finally {
          importSheetsRef.current = null;
        }
      })();
    },
    [runImport],
  );

  useEffect(() => {
    const carryFiles = (event: DragEvent) =>
      !!event.dataTransfer && Array.from(event.dataTransfer.types).includes('Files');

    const onDragOver = (event: DragEvent) => {
      if (!carryFiles(event)) {
        return;
      }
      event.preventDefault();
      if (event.dataTransfer) {
        event.dataTransfer.dropEffect = 'copy';
      }
      setDragActive(true);
    };

    const onDragLeave = (event: DragEvent) => {
      if (!event.relatedTarget) {
        setDragActive(false);
      }
    };

    const onDrop = (event: DragEvent) => {
      if (!carryFiles(event)) {
        return;
      }
      // Keep FortuneSheet from treating the drop as a cell gesture.
      event.preventDefault();
      event.stopPropagation();
      setDragActive(false);
      const files = Array.from(event.dataTransfer?.files ?? []);
      if (files.length) {
        void handleDroppedFiles(files);
      }
    };

    window.addEventListener('dragover', onDragOver, true);
    window.addEventListener('dragleave', onDragLeave, true);
    window.addEventListener('drop', onDrop, true);
    return () => {
      window.removeEventListener('dragover', onDragOver, true);
      window.removeEventListener('dragleave', onDragLeave, true);
      window.removeEventListener('drop', onDrop, true);
    };
  }, [handleDroppedFiles]);

  /* ---------------------------------------------------------------- */
  /* AI answer insertion                                               */
  /* ---------------------------------------------------------------- */

  const insertIntoCurrentMode = useCallback(
    (text: string): OperationResult => {
      switch (modeRef.current) {
        case 'spreadsheet':
          return spreadsheetAdapter.insertText(text);
        case 'document':
          documentAdapter.insertText(text);
          return { ok: true, message: 'Word 文書に挿入しました' };
        default:
          return presentationAdapter.insertText(text);
      }
    },
    [documentAdapter, presentationAdapter, spreadsheetAdapter],
  );

  const planAction = useCallback(
    (text: string, action: string): OperationResult => {
      switch (action) {
        case 'text':
          return { ok: true, needsConfirm: false, message: '現在のモードへテキストとして挿入します。' };

        case 'table': {
          const table = parseTable(text);
          if (!table) {
            return {
              ok: false,
              error:
                '表として解析できませんでした。Markdown 表・CSV・TSV のいずれの形式でもありません。',
            };
          }
          const plan = spreadsheetAdapter.planTable(table.rows);
          if (!plan.ok) {
            return plan;
          }
          return {
            ...plan,
            ok: true,
            rows: table.rows.length,
            columns: table.rows[0].length,
          };
        }

        case 'document':
          return { ok: true, needsConfirm: false, message: 'Word 文書へ挿入します。' };

        case 'slides': {
          const slides = markdownToSlides(text);
          if (!slides.length) {
            return {
              ok: false,
              error: 'スライドを生成できませんでした。見出しを含むテキストが必要です。',
            };
          }
          return {
            ok: true,
            needsConfirm: true,
            count: slides.length,
            message: `${slides.length} 枚のスライドを末尾に追加します。既存のスライドは削除されません。よろしいですか？\n（追加後も自由に編集できます）`,
          };
        }

        default:
          return { ok: false, error: `不明な操作です: ${action}` };
      }
    },
    [spreadsheetAdapter],
  );

  const applyAction = useCallback(
    (text: string, action: string, confirmed: boolean): OperationResult => {
      switch (action) {
        case 'text': {
          const result = insertIntoCurrentMode(text);
          if (result.ok) {
            notifyContentChanged();
          }
          return result;
        }

        case 'table': {
          const table = parseTable(text);
          if (!table) {
            return { ok: false, error: '表として解析できませんでした。' };
          }
          const plan = spreadsheetAdapter.planTable(table.rows);
          if (!plan.ok) {
            return plan;
          }
          if (!confirmed && plan.needsConfirm) {
            return { ok: false, error: '既存データの上書き確認が必要です。' };
          }
          applyMode('spreadsheet');
          const result = spreadsheetAdapter.insertTable(table.rows);
          if (result.ok) {
            notifyContentChanged();
            notifyStatus(result.message ?? '表を挿入しました');
          }
          return result;
        }

        case 'document': {
          applyMode('document');
          documentAdapter.insertMarkdown(text);
          notifyContentChanged();
          notifyStatus('AI 回答を Word 文書へ挿入しました');
          return { ok: true, message: 'AI 回答を Word 文書へ挿入しました' };
        }

        case 'slides': {
          const slides = markdownToSlides(text);
          if (!slides.length) {
            return { ok: false, error: 'スライドを生成できませんでした。' };
          }
          applyMode('slides');
          const result = presentationAdapter.appendSlides(slides);
          if (result.ok) {
            notifyContentChanged();
            notifyStatus(result.message ?? 'スライドを追加しました');
          }
          return result;
        }

        default:
          return { ok: false, error: `不明な操作です: ${action}` };
      }
    },
    [
      applyMode,
      documentAdapter,
      insertIntoCurrentMode,
      presentationAdapter,
      spreadsheetAdapter,
    ],
  );

  /* ---------------------------------------------------------------- */
  /* JavaScript API used by Python                                     */
  /* ---------------------------------------------------------------- */

  const api = useMemo<OfficeEditorApi>(
    () => ({
      isReady: () => readyRef.current,

      insertText: (text) => {
        if (typeof text !== 'string') {
          return JSON.stringify({ ok: false, error: 'テキストが文字列ではありません。' });
        }
        const result = insertIntoCurrentMode(text);
        if (result.ok) {
          notifyContentChanged();
        }
        return JSON.stringify(result);
      },

      getContent: () => JSON.stringify(contentForMode(modeRef.current)),

      getAllContent: () => JSON.stringify(buildProject()),

      setContent: (data) => JSON.stringify(applyProject(data)),

      setMode: (next) => {
        if (!isMode(next)) {
          return JSON.stringify({ ok: false, error: `不明なモードです: ${String(next)}` });
        }
        applyMode(next);
        return JSON.stringify({ ok: true, message: `${MODE_LABELS[next]} モードに切り替えました` });
      },

      getMode: () => modeRef.current,

      planAiResponse: (text, action) =>
        JSON.stringify(planAction(String(text ?? ''), String(action ?? ''))),

      applyAiResponse: (text, action, confirmed) =>
        JSON.stringify(applyAction(String(text ?? ''), String(action ?? ''), Boolean(confirmed))),

      importFile: (fileName, base64) => {
        const name = String(fileName ?? '');
        importBase64(name, String(base64 ?? ''));
        return JSON.stringify({ ok: true, message: `${name} を読み込みます` });
      },
    }),
    [
      applyAction,
      applyMode,
      applyProject,
      buildProject,
      contentForMode,
      importBase64,
      insertIntoCurrentMode,
      planAction,
    ],
  );

  const apiRef = useRef<OfficeEditorApi>(api);
  apiRef.current = api;

  useEffect(() => {
    installOfficeApi(() => apiRef.current);
  }, []);

  const handleContentChanged = useCallback(() => {
    notifyContentChanged();
  }, []);

  return (
    <div className="app">
      <header className="app-header">
        <div className="mode-tabs" role="tablist" aria-label="エディタモード">
          {MODES.map((value) => (
            <button
              key={value}
              type="button"
              role="tab"
              aria-selected={mode === value}
              className={`mode-tab${mode === value ? ' is-active' : ''}`}
              onClick={() => applyMode(value)}
            >
              {MODE_LABELS[value]}
            </button>
          ))}
        </div>
        <div className="app-header-meta">
          <button type="button" className="tb-button" onClick={() => setGooglePanelOpen(true)}>
            Google ファイル
          </button>
          {bridgeState === 'standalone' ? (
            <span className="badge muted" title="Qt の QWebChannel に接続されていません">
              Python 未接続
            </span>
          ) : null}
          <span className="badge">{mode === 'spreadsheet' ? 'Excel' : mode === 'document' ? 'Word' : 'Slide'}</span>
        </div>
      </header>

      <div className="editor-stage">
        <div className="mode-layer" data-active={mode === 'spreadsheet'}>
          <SpreadsheetEditor ref={spreadsheetRef} onChange={handleContentChanged} />
        </div>
        <div className="mode-layer" data-active={mode === 'document'}>
          <DocumentEditor ref={documentRef} onChange={handleContentChanged} />
        </div>
        <div className="mode-layer" data-active={mode === 'slides'}>
          <PresentationEditor ref={presentationRef} onChange={handleContentChanged} />
        </div>
      </div>

      {dragActive ? (
        <div className="drop-hint" aria-hidden="true">
          <div className="drop-hint-card">
            ここにファイルをドロップ
            <small>{supportedImportNames()} を追加できます</small>
          </div>
        </div>
      ) : null}
      {googlePanelOpen ? <GoogleEmbedPanel onClose={() => setGooglePanelOpen(false)} /> : null}
    </div>
  );
}
