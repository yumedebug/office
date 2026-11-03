import type { JSONContent } from '@tiptap/core';
import type { DocumentHandle } from '../types';
import { textToParagraphNodes } from '../utils/converters';
import { markdownToNodes } from '../utils/markdownParser';

export interface DocumentAdapter {
  getData(): JSONContent | null;
  setData(content: JSONContent | null): boolean;
  insertText(text: string): void;
  insertMarkdown(markdown: string): void;
  /** Append already-built Tiptap nodes at the end of the document. */
  appendNodes(nodes: JSONContent[]): void;
  focusEditor(): void;
}

export function createDocumentAdapter(getHandle: () => DocumentHandle | null): DocumentAdapter {
  const getEditor = () => getHandle()?.getEditor() ?? null;

  return {
    getData: () => {
      const editor = getEditor();
      if (!editor) {
        return null;
      }
      try {
        return editor.getJSON();
      } catch (error) {
        console.warn('[documentAdapter] 文書データを取得できませんでした', error);
        return null;
      }
    },

    setData: (content) => {
      const handle = getHandle();
      if (!handle) {
        return false;
      }
      handle.setContent(content);
      return true;
    },

    insertText: (text) => {
      const editor = getEditor();
      if (!editor) {
        return;
      }
      const nodes = textToParagraphNodes(text);
      if (!nodes.length) {
        return;
      }
      // Do not force focus: the editor can still be hidden when the mode was
      // switched in the same render, and focus() would be dropped.
      editor.chain().insertContent(nodes).run();
    },

    insertMarkdown: (markdown) => {
      const editor = getEditor();
      if (!editor) {
        return;
      }
      const nodes = markdownToNodes(markdown);
      if (!nodes.length) {
        return;
      }
      editor.chain().insertContent(nodes).run();
    },

    appendNodes: (nodes) => {
      const editor = getEditor();
      if (!editor || !nodes.length) {
        return;
      }
      // Insert at the document end explicitly: focus('end') is unreliable when
      // the Word layer is hidden behind another mode.
      editor.chain().insertContentAt(editor.state.doc.content.size, nodes).run();
    },

    focusEditor: () => {
      getEditor()?.commands.focus();
    },
  };
}
