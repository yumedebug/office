import { forwardRef, useImperativeHandle, useState } from 'react';
import { EditorContent, useEditor } from '@tiptap/react';
import StarterKit from '@tiptap/starter-kit';
import { BackgroundColor, Color, TextStyle } from '@tiptap/extension-text-style';
import Highlight from '@tiptap/extension-highlight';
import TextAlign from '@tiptap/extension-text-align';
import type { JSONContent } from '@tiptap/core';
import { EMPTY_DOCUMENT, type DocumentHandle } from '../types';

interface DocumentEditorProps {
  initialContent?: JSONContent | null;
  onChange?: () => void;
}

const TEXT_COLORS = ['#111318', '#5B8DEF', '#1D4ED8', '#0F766E', '#B91C1C', '#7C3AED', '#B45309', '#6B7280'];
const HIGHLIGHT_COLORS = ['#FFF3BF', '#FFD8A8', '#B2F2BB', '#BAE6FD', '#E9D5FF', '#FFC9C9', '#EEF3FB', '#FFFFFF'];

interface ToolbarButtonProps {
  label: string;
  title: string;
  active?: boolean;
  disabled?: boolean;
  onClick: () => void;
}

function ToolbarButton({ label, title, active, disabled, onClick }: ToolbarButtonProps) {
  return (
    <button
      type="button"
      className={`tb-button${active ? ' is-active' : ''}`}
      title={title}
      aria-label={title}
      disabled={disabled}
      onMouseDown={(event) => event.preventDefault()}
      onClick={onClick}
    >
      {label}
    </button>
  );
}

const DocumentEditor = forwardRef<DocumentHandle, DocumentEditorProps>(
  function DocumentEditor({ initialContent, onChange }, ref) {
    const editor = useEditor({
      extensions: [
        StarterKit.configure({
          link: {
            openOnClick: false,
            autolink: true,
            HTMLAttributes: { rel: 'noopener noreferrer', target: '_blank' },
          },
        }),
        TextStyle,
        Color,
        BackgroundColor,
        Highlight.configure({ multicolor: true }),
        TextAlign.configure({ types: ['heading', 'paragraph'] }),
      ],
      content: initialContent ?? EMPTY_DOCUMENT,
      shouldRerenderOnTransaction: true,
      editorProps: {
        attributes: { class: 'doc-prose', spellcheck: 'false' },
      },
      onUpdate: () => {
        onChange?.();
      },
    });

    const [linkDraft, setLinkDraft] = useState<string | null>(null);
    const [palette, setPalette] = useState<'text' | 'highlight' | null>(null);

    useImperativeHandle(
      ref,
      () => ({
        getEditor: () => editor ?? null,
        setContent: (content: JSONContent | null) => {
          editor?.commands.setContent(content ?? EMPTY_DOCUMENT, { emitUpdate: false });
        },
      }),
      [editor],
    );

    if (!editor) {
      return null;
    }

    const applyLink = () => {
      const value = (linkDraft ?? '').trim();
      if (!value) {
        editor.chain().focus().extendMarkRange('link').unsetLink().run();
      } else {
        const href = /^(https?:\/\/|mailto:)/i.test(value) ? value : `https://${value}`;
        editor
          .chain()
          .focus()
          .extendMarkRange('link')
          .setLink({ href, target: '_blank', rel: 'noopener noreferrer' })
          .run();
      }
      setLinkDraft(null);
    };

    const openLinkEditor = () => {
      const attributes = editor.getAttributes('link') as { href?: unknown };
      setLinkDraft(typeof attributes.href === 'string' ? attributes.href : '');
    };

    return (
      <div className="document-mode">
        <div className="doc-toolbar">
          <div className="tb-group">
            <ToolbarButton
              label="↶"
              title="元に戻す"
              disabled={!editor.can().undo()}
              onClick={() => editor.chain().focus().undo().run()}
            />
            <ToolbarButton
              label="↷"
              title="やり直す"
              disabled={!editor.can().redo()}
              onClick={() => editor.chain().focus().redo().run()}
            />
          </div>

          <div className="tb-group">
            <ToolbarButton
              label="H1"
              title="見出し1"
              active={editor.isActive('heading', { level: 1 })}
              onClick={() => editor.chain().focus().toggleHeading({ level: 1 }).run()}
            />
            <ToolbarButton
              label="H2"
              title="見出し2"
              active={editor.isActive('heading', { level: 2 })}
              onClick={() => editor.chain().focus().toggleHeading({ level: 2 }).run()}
            />
            <ToolbarButton
              label="H3"
              title="見出し3"
              active={editor.isActive('heading', { level: 3 })}
              onClick={() => editor.chain().focus().toggleHeading({ level: 3 }).run()}
            />
            <ToolbarButton
              label="¶"
              title="本文"
              active={editor.isActive('paragraph')}
              onClick={() => editor.chain().focus().setParagraph().run()}
            />
          </div>

          <div className="tb-group">
            <ToolbarButton
              label="B"
              title="太字"
              active={editor.isActive('bold')}
              onClick={() => editor.chain().focus().toggleBold().run()}
            />
            <ToolbarButton
              label="I"
              title="斜体"
              active={editor.isActive('italic')}
              onClick={() => editor.chain().focus().toggleItalic().run()}
            />
            <ToolbarButton
              label="U"
              title="下線"
              active={editor.isActive('underline')}
              onClick={() => editor.chain().focus().toggleUnderline().run()}
            />
            <ToolbarButton
              label="S"
              title="取り消し線"
              active={editor.isActive('strike')}
              onClick={() => editor.chain().focus().toggleStrike().run()}
            />
            <ToolbarButton
              label="`"
              title="インラインコード"
              active={editor.isActive('code')}
              onClick={() => editor.chain().focus().toggleCode().run()}
            />
          </div>

          <div className="tb-group">
            <ToolbarButton
              label="•"
              title="箇条書き"
              active={editor.isActive('bulletList')}
              onClick={() => editor.chain().focus().toggleBulletList().run()}
            />
            <ToolbarButton
              label="1."
              title="番号付きリスト"
              active={editor.isActive('orderedList')}
              onClick={() => editor.chain().focus().toggleOrderedList().run()}
            />
            <ToolbarButton
              label="❝"
              title="引用"
              active={editor.isActive('blockquote')}
              onClick={() => editor.chain().focus().toggleBlockquote().run()}
            />
            <ToolbarButton
              label="⛓"
              title="リンク"
              active={editor.isActive('link')}
              onClick={openLinkEditor}
            />
          </div>

          <div className="tb-group">
            <ToolbarButton
              label="A"
              title="文字色"
              active={palette === 'text'}
              onClick={() => setPalette(palette === 'text' ? null : 'text')}
            />
            <ToolbarButton
              label="▮"
              title="背景色"
              active={palette === 'highlight'}
              onClick={() => setPalette(palette === 'highlight' ? null : 'highlight')}
            />
          </div>

          <div className="tb-group">
            <ToolbarButton
              label="左"
              title="左揃え"
              active={editor.isActive({ textAlign: 'left' })}
              onClick={() => editor.chain().focus().setTextAlign('left').run()}
            />
            <ToolbarButton
              label="中"
              title="中央揃え"
              active={editor.isActive({ textAlign: 'center' })}
              onClick={() => editor.chain().focus().setTextAlign('center').run()}
            />
            <ToolbarButton
              label="右"
              title="右揃え"
              active={editor.isActive({ textAlign: 'right' })}
              onClick={() => editor.chain().focus().setTextAlign('right').run()}
            />
            <ToolbarButton
              label="両"
              title="両端揃え"
              active={editor.isActive({ textAlign: 'justify' })}
              onClick={() => editor.chain().focus().setTextAlign('justify').run()}
            />
          </div>
        </div>

        {linkDraft !== null && (
          <div className="link-editor">
            <span>リンク URL</span>
            <input
              type="text"
              value={linkDraft}
              autoFocus
              placeholder="https://example.com"
              onChange={(event) => setLinkDraft(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === 'Enter') {
                  event.preventDefault();
                  applyLink();
                }
                if (event.key === 'Escape') {
                  setLinkDraft(null);
                }
              }}
            />
            <button type="button" className="tb-button primary" onClick={applyLink}>
              適用
            </button>
            <button
              type="button"
              className="tb-button"
              onClick={() => {
                editor.chain().focus().extendMarkRange('link').unsetLink().run();
                setLinkDraft(null);
              }}
            >
              解除
            </button>
            <button type="button" className="tb-button" onClick={() => setLinkDraft(null)}>
              閉じる
            </button>
          </div>
        )}

        {palette === 'text' && (
          <div className="palette-row">
            {TEXT_COLORS.map((color) => (
              <button
                key={color}
                type="button"
                className="swatch"
                style={{ backgroundColor: color }}
                title={`文字色 ${color}`}
                onClick={() => {
                  editor.chain().focus().setColor(color).run();
                  setPalette(null);
                }}
              />
            ))}
            <button
              type="button"
              className="tb-button"
              onClick={() => {
                editor.chain().focus().unsetColor().run();
                setPalette(null);
              }}
            >
              既定
            </button>
          </div>
        )}

        {palette === 'highlight' && (
          <div className="palette-row">
            {HIGHLIGHT_COLORS.map((color) => (
              <button
                key={color}
                type="button"
                className="swatch"
                style={{ backgroundColor: color }}
                title={`背景色 ${color}`}
                onClick={() => {
                  editor.chain().focus().toggleHighlight({ color }).run();
                  setPalette(null);
                }}
              />
            ))}
            <button
              type="button"
              className="tb-button"
              onClick={() => {
                editor.chain().focus().unsetHighlight().run();
                setPalette(null);
              }}
            >
              解除
            </button>
          </div>
        )}

        <div className="doc-scroll">
          <div className="doc-paper">
            <EditorContent editor={editor} />
          </div>
        </div>
      </div>
    );
  },
);

export default DocumentEditor;
