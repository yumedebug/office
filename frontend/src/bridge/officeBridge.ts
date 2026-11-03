import type { OfficeEditorApi } from '../types';

/**
 * The object that Python registers as ``officeBridge``.  QWebChannel wraps it
 * so every method returns a promise; errors are handled by the caller.
 */
export interface BridgeObject {
  editorReady(): void;
  contentChanged(): void;
  showStatus(message: string): void;
  reportError(message: string): void;
  requestSave(): void;
  modeChanged(mode: string): void;
}

interface WebChannelChannel {
  objects?: Record<string, BridgeObject>;
}

type QWebChannelConstructor = new (
  transport: unknown,
  callback: (channel: WebChannelChannel) => void,
) => unknown;

interface QtGlobals {
  QWebChannel?: QWebChannelConstructor;
  qt?: { webChannelTransport?: unknown };
}

const QT = window as unknown as QtGlobals;

let bridge: BridgeObject | null = null;
let changeTimer: number | null = null;
let suppressUntil = 0;

/* ------------------------------------------------------------------ */
/* Loading Qt's own qwebchannel.js                                     */
/* ------------------------------------------------------------------ */

function loadQWebChannelScript(): Promise<void> {
  return new Promise((resolve, reject) => {
    if (typeof QT.QWebChannel === 'function') {
      resolve();
      return;
    }

    const existing = document.querySelector<HTMLScriptElement>('script[data-qwebchannel]');
    if (existing) {
      existing.addEventListener('load', () => resolve());
      existing.addEventListener('error', () => reject(new Error('qtwebchannel.js の読み込みに失敗しました')));
      return;
    }

    const script = document.createElement('script');
    script.src = './qtwebchannel.js';
    script.async = true;
    script.dataset.qwebchannel = '1';
    script.addEventListener('load', () => resolve());
    script.addEventListener('error', () => reject(new Error('qtwebchannel.js が見つかりません')));
    document.head.appendChild(script);
  });
}

/**
 * Connect to the Python side.  Returns ``false`` when the page runs in a plain
 * browser (``npm run dev``) where no Qt transport exists.
 */
export async function connectBridge(): Promise<boolean> {
  try {
    await loadQWebChannelScript();
  } catch (error) {
    // A missing script is not fatal: the editors still work without Python.
    console.warn('[officeBridge]', error);
    return false;
  }

  if (typeof QT.QWebChannel !== 'function' || !QT.qt || !QT.qt.webChannelTransport) {
    return false;
  }

  const constructor = QT.QWebChannel;
  return new Promise<boolean>((resolve) => {
    try {
      new constructor(QT.qt?.webChannelTransport, (channel) => {
        bridge = channel.objects?.officeBridge ?? null;
        resolve(bridge !== null);
      });
    } catch (error) {
      console.error('[officeBridge] QWebChannel の初期化に失敗しました', error);
      resolve(false);
    }
  });
}

export function getBridge(): BridgeObject | null {
  return bridge;
}

/* ------------------------------------------------------------------ */
/* Notifications (JavaScript -> Python)                                */
/* ------------------------------------------------------------------ */

/** Tell Python that the React app finished initialising. */
export function notifyReady(): void {
  if (!bridge) {
    return;
  }
  bridge.editorReady();
  if (changeTimer !== null) {
    window.clearTimeout(changeTimer);
    changeTimer = null;
  }
}

/**
 * Ignore change notifications for a short window.  Loading a project replaces
 * the FortuneSheet workbook, and its remount must not be reported as a user
 * edit (that would mark a freshly opened project as dirty).
 */
export function suppressContentNotifications(ms = 1500): void {
  suppressUntil = Date.now() + ms;
}

/** Debounced so typing does not flood the QWebChannel. */
export function notifyContentChanged(): void {
  if (!bridge || Date.now() < suppressUntil) {
    return;
  }
  if (changeTimer !== null) {
    window.clearTimeout(changeTimer);
  }
  changeTimer = window.setTimeout(() => {
    changeTimer = null;
    bridge?.contentChanged();
  }, 500);
}

export function notifyStatus(message: string): void {
  bridge?.showStatus(message);
}

export function notifyError(message: string): void {
  bridge?.reportError(message);
}

export function notifyModeChanged(mode: string): void {
  bridge?.modeChanged(mode);
}

/** Ask the host application to run its save command. */
export function notifySaveRequest(): void {
  bridge?.requestSave();
}

/* ------------------------------------------------------------------ */
/* window.officeEditor                                                 */
/* ------------------------------------------------------------------ */

/**
 * Install ``window.officeEditor`` once.  Every call is forwarded to the latest
 * React implementation through ``getApi`` so the reference never goes stale
 * after a re-render.
 */
export function installOfficeApi(getApi: () => OfficeEditorApi): void {
  const proxy: OfficeEditorApi = {
    insertText: (text) => getApi().insertText(text),
    getContent: () => getApi().getContent(),
    getAllContent: () => getApi().getAllContent(),
    setContent: (data) => getApi().setContent(data),
    setMode: (mode) => getApi().setMode(mode),
    getMode: () => getApi().getMode(),
    isReady: () => getApi().isReady(),
    planAiResponse: (text, action) => getApi().planAiResponse(text, action),
    applyAiResponse: (text, action, confirmed) => getApi().applyAiResponse(text, action, confirmed),
    importFile: (fileName, base64) => getApi().importFile(fileName, base64),
  };
  window.officeEditor = proxy;
}
