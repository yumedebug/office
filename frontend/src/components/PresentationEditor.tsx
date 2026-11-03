import {
  forwardRef,
  useCallback,
  useEffect,
  useImperativeHandle,
  useRef,
  useState,
} from 'react';
import type { PointerEvent as ReactPointerEvent } from 'react';
import Reveal from 'reveal.js';
import type { RevealApi, RevealConfig } from 'reveal.js';
import 'reveal.js/reveal.css';
import type { PresentationHandle, SlideData, SlideElement, SlideLayout } from '../types';
import {
  DEFAULT_SLIDE_BACKGROUND,
  LAYOUT_LABELS,
  SLIDE_BACKGROUNDS,
  SLIDE_LAYOUTS,
  contrastingText,
  createSlide,
  createSlideElementId,
  ensureSlides,
} from '../utils/converters';

interface PresentationEditorProps {
  initialSlides?: SlideData[];
  onChange?: () => void;
}

/* ------------------------------------------------------------------ */
/* Presentation overlay (Reveal.js)                                    */
/* ------------------------------------------------------------------ */

interface PresentationOverlayProps {
  slides: SlideData[];
  startIndex: number;
  onClose: () => void;
}

function PresentationOverlay({ slides, startIndex, onClose }: PresentationOverlayProps) {
  const elementRef = useRef<HTMLDivElement | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const element = elementRef.current;
    if (!element) {
      return undefined;
    }

    const config = {
      embedded: true,
      hash: false,
      controls: true,
      progress: true,
      keyboard: true,
      center: true,
      transition: 'slide',
      width: 1280,
      height: 720,
      margin: 0.04,
      minScale: 0.2,
      maxScale: 1.4,
      slideNumber: true,
    } as RevealConfig;

    let deck: RevealApi | null = null;
    let disposed = false;

    try {
      deck = new Reveal(element, config);
      deck
        .initialize()
        .then(() => {
          if (!disposed && deck) {
            const target = Math.min(Math.max(startIndex, 0), Math.max(slides.length - 1, 0));
            deck.slide(target, 0);
          }
        })
        .catch((reason: unknown) => {
          if (!disposed) {
            setError(reason instanceof Error ? reason.message : String(reason));
          }
        });
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    }

    return () => {
      disposed = true;
      try {
        deck?.destroy();
      } catch (reason) {
        console.warn('[presentation] Reveal.js の終了処理に失敗しました', reason);
      }
    };
  }, [slides, startIndex]);

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        event.preventDefault();
        onClose();
      }
    };
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, [onClose]);

  return (
    <div className="presentation-overlay">
      <div className="reveal" ref={elementRef}>
        <div className="slides">
          {slides.map((slide) => (
            <section
              key={slide.id}
              data-layout={slide.layout}
              style={{ backgroundColor: slide.background, color: contrastingText(slide.background) }}
            >
              {slide.layout !== 'blank' && slide.title ? <h2>{slide.title}</h2> : null}
              {slide.layout !== 'blank'
                ? slide.body
                    .split('\n')
                    .filter((line) => line.trim().length > 0)
                    .map((line, index) => <p key={`${slide.id}-line-${index}`}>{line}</p>)
                : null}
            </section>
          ))}
        </div>
      </div>
      {error ? <p className="present-error">プレゼンテーションを開始できません: {error}</p> : null}
      <button type="button" className="present-close" onClick={onClose}>
        閉じる (Esc)
      </button>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/* Slide editor                                                        */
/* ------------------------------------------------------------------ */

const PresentationEditor = forwardRef<PresentationHandle, PresentationEditorProps>(
  function PresentationEditor({ initialSlides, onChange }, ref) {
    const [slides, setSlides] = useState<SlideData[]>(() =>
      initialSlides && initialSlides.length
        ? ensureSlides(initialSlides)
        : [createSlide({ title: 'Title', body: '本文を入力してください', layout: 'title-content' })],
    );
    const [activeIndex, setActiveIndexState] = useState(0);
    const [presenting, setPresenting] = useState(false);
    const [selectedElementId, setSelectedElementId] = useState<string | null>(null);
    const pointerRef = useRef<{
      id: string;
      mode: 'move' | 'resize';
      startX: number;
      startY: number;
      element: SlideElement;
    } | null>(null);

    const slidesRef = useRef<SlideData[]>(slides);
    slidesRef.current = slides;
    const activeRef = useRef<number>(activeIndex);
    activeRef.current = activeIndex;

    const updateSlides = useCallback(
      (next: SlideData[], options?: { notify?: boolean }) => {
        setSlides(next);
        slidesRef.current = next;
        if (options?.notify !== false) {
          onChange?.();
        }
      },
      [onChange],
    );

    const setActive = useCallback((index: number) => {
      const bounded = Math.min(Math.max(index, 0), Math.max(slidesRef.current.length - 1, 0));
      setActiveIndexState(bounded);
      activeRef.current = bounded;
    }, []);

    useImperativeHandle(
      ref,
      () => ({
        getSlides: () => slidesRef.current,
        setSlides: (next: SlideData[]) => {
          const cleaned = ensureSlides(next);
          const list = cleaned.length ? cleaned : [createSlide({ title: 'Title', body: '' })];
          updateSlides(list, { notify: false });
          setActive(0);
        },
        getActiveIndex: () => activeRef.current,
        setActiveIndex: (index: number) => setActive(index),
      }),
      [setActive, updateSlides],
    );

    const active = slides[Math.min(Math.max(activeIndex, 0), Math.max(slides.length - 1, 0))];

    const updateActive = (patch: Partial<SlideData>) => {
      const index = activeRef.current;
      const next = slidesRef.current.map((slide, position) =>
        position === index ? { ...slide, ...patch } : slide,
      );
      updateSlides(next);
    };

    const updateElement = (id: string, patch: Partial<SlideElement>) => {
      const current = slidesRef.current[activeRef.current];
      if (!current) {
        return;
      }
      const elements = (current.elements ?? []).map((element) =>
        element.id === id ? { ...element, ...patch } : element,
      );
      updateActive({ elements });
    };

    const addElement = (kind: 'text' | 'shape') => {
      const element: SlideElement = {
        id: createSlideElementId(),
        kind,
        text: kind === 'text' ? 'テキストを入力' : '',
        x: 12,
        y: 18,
        width: kind === 'text' ? 34 : 24,
        height: kind === 'text' ? 12 : 20,
        color: '#1A1D22',
        background: kind === 'shape' ? '#DCE6F8' : undefined,
      };
      updateActive({ elements: [...(active.elements ?? []), element] });
      setSelectedElementId(element.id);
    };

    const removeElement = () => {
      if (!selectedElementId) {
        return;
      }
      updateActive({
        elements: (active.elements ?? []).filter((element) => element.id !== selectedElementId),
      });
      setSelectedElementId(null);
    };

    const onElementPointerDown = (
      event: ReactPointerEvent<HTMLElement>,
      element: SlideElement,
      mode: 'move' | 'resize' = 'move',
    ) => {
      event.stopPropagation();
      event.currentTarget.setPointerCapture(event.pointerId);
      setSelectedElementId(element.id);
      pointerRef.current = {
        id: element.id,
        mode,
        startX: event.clientX,
        startY: event.clientY,
        element: { ...element },
      };
    };

    const onCanvasPointerMove = (event: ReactPointerEvent<HTMLElement>) => {
      const pointer = pointerRef.current;
      const canvas = event.currentTarget;
      if (!pointer || !canvas) {
        return;
      }
      const rect = canvas.getBoundingClientRect();
      const dx = ((event.clientX - pointer.startX) / rect.width) * 100;
      const dy = ((event.clientY - pointer.startY) / rect.height) * 100;
      let patch: Partial<SlideElement>;
      if (pointer.mode === 'resize') {
        patch = {
          width: Math.min(95 - pointer.element.x, Math.max(8, pointer.element.width + dx)),
          height: Math.min(95 - pointer.element.y, Math.max(6, pointer.element.height + dy)),
        };
      } else {
        patch = {
          x: Math.min(95 - pointer.element.width, Math.max(0, pointer.element.x + dx)),
          y: Math.min(95 - pointer.element.height, Math.max(0, pointer.element.y + dy)),
        };
      }
      updateElement(pointer.id, patch);
      pointerRef.current = {
        ...pointer,
        startX: event.clientX,
        startY: event.clientY,
        element: { ...pointer.element, ...patch },
      };
    };

    const stopElementPointer = () => {
      pointerRef.current = null;
    };

    const addSlide = () => {
      const list = slidesRef.current;
      const insertAt = activeRef.current + 1;
      const next = [
        ...list.slice(0, insertAt),
        createSlide({ title: `Slide ${list.length + 1}`, body: '' }),
        ...list.slice(insertAt),
      ];
      updateSlides(next);
      setActive(insertAt);
    };

    const duplicateSlide = () => {
      const list = slidesRef.current;
      const source = list[activeRef.current];
      if (!source) {
        return;
      }
      const copy = createSlide({ ...source, id: undefined });
      const insertAt = activeRef.current + 1;
      const next = [...list.slice(0, insertAt), copy, ...list.slice(insertAt)];
      updateSlides(next);
      setActive(insertAt);
    };

    const removeSlide = () => {
      const list = slidesRef.current;
      const next = list.filter((_slide, position) => position !== activeRef.current);
      if (!next.length) {
        next.push(createSlide({ title: 'Title', body: '' }));
      }
      updateSlides(next);
      setActive(Math.max(0, activeRef.current - 1));
    };

    const moveSlide = (offset: -1 | 1) => {
      const list = [...slidesRef.current];
      const from = activeRef.current;
      const to = from + offset;
      if (to < 0 || to >= list.length) {
        return;
      }
      const [moved] = list.splice(from, 1);
      list.splice(to, 0, moved);
      updateSlides(list);
      setActive(to);
    };

    return (
      <div className="slide-mode">
        <div className="slide-toolbar">
          <button type="button" className="tb-button" onClick={addSlide}>
            スライド追加
          </button>
          <button type="button" className="tb-button" onClick={duplicateSlide}>
            複製
          </button>
          <button type="button" className="tb-button" onClick={() => addElement('text')}>
            テキスト追加
          </button>
          <button type="button" className="tb-button" onClick={() => addElement('shape')}>
            図形追加
          </button>
          <button
            type="button"
            className="tb-button danger"
            disabled={!selectedElementId}
            onClick={removeElement}
          >
            要素削除
          </button>
          <button type="button" className="tb-button danger" onClick={removeSlide}>
            削除
          </button>
          <span className="tb-separator" />
          <button
            type="button"
            className="tb-button"
            disabled={activeIndex <= 0}
            onClick={() => moveSlide(-1)}
          >
            ↑ 前へ移動
          </button>
          <button
            type="button"
            className="tb-button"
            disabled={activeIndex >= slides.length - 1}
            onClick={() => moveSlide(1)}
          >
            ↓ 後ろへ移動
          </button>
          <span className="tb-separator" />
          <button type="button" className="tb-button primary" onClick={() => setPresenting(true)}>
            プレゼンテーション
          </button>
        </div>

        <div className="slide-body">
          <aside className="slide-list" aria-label="スライド一覧">
            {slides.map((slide, index) => (
              <button
                key={slide.id}
                type="button"
                className={`slide-list-item${index === activeIndex ? ' is-active' : ''}`}
                onClick={() => setActive(index)}
              >
                <span className="slide-index">{index + 1}</span>
                <span className="slide-list-text">
                  <span className="slide-list-title">{slide.title || '(無題)'}</span>
                  <span className="slide-list-layout">{LAYOUT_LABELS[slide.layout]}</span>
                </span>
                <span
                  className="slide-list-swatch"
                  style={{ backgroundColor: slide.background }}
                  aria-hidden="true"
                />
              </button>
            ))}
          </aside>

          <section className="slide-main">
            <div className="slide-canvas-wrap">
              <div
                className="slide-canvas"
                data-layout={active ? active.layout : 'title-content'}
                onPointerMove={onCanvasPointerMove}
                onPointerUp={stopElementPointer}
                onPointerCancel={stopElementPointer}
                onPointerDown={() => setSelectedElementId(null)}
                style={{
                  backgroundColor: active ? active.background : DEFAULT_SLIDE_BACKGROUND,
                  color: active ? contrastingText(active.background) : '#1A1D22',
                }}
              >
                {active ? (
                  <>
                    {active.layout !== 'blank' ? (
                      <h2 className="slide-canvas-title">{active.title || ' '}</h2>
                    ) : null}
                    {active.layout !== 'blank' && active.layout !== 'title-only' ? (
                      <div className="slide-canvas-body">
                        {active.body
                          .split('\n')
                          .filter((line) => line.trim().length > 0)
                          .map((line, index) => (
                            <p key={`preview-${active.id}-${index}`}>{line}</p>
                          ))}
                      </div>
                    ) : null}
                    {(active.elements ?? []).map((element) => (
                      <div
                        key={element.id}
                        className={`slide-element slide-element-${element.kind}${
                          selectedElementId === element.id ? ' is-selected' : ''
                        }`}
                        style={{
                          left: `${element.x}%`,
                          top: `${element.y}%`,
                          width: `${element.width}%`,
                          height: `${element.height}%`,
                          color: element.color,
                          backgroundColor: element.background,
                        }}
                        onPointerDown={(event) => onElementPointerDown(event, element)}
                        onDoubleClick={() => {
                          if (element.kind === 'text') {
                            const text = window.prompt('テキスト', element.text);
                            if (text !== null) {
                              updateElement(element.id, { text });
                            }
                          }
                        }}
                      >
                        {element.text}
                        {selectedElementId === element.id ? (
                          <span
                            className="slide-element-handle"
                            onPointerDown={(event) => onElementPointerDown(event, element, 'resize')}
                          />
                        ) : null}
                      </div>
                    ))}
                  </>
                ) : null}
              </div>
            </div>

            {active ? (
              <div className="slide-form">
                <label className="field">
                  <span>タイトル</span>
                  <input
                    type="text"
                    value={active.title}
                    onChange={(event) => updateActive({ title: event.target.value })}
                  />
                </label>
                <label className="field">
                  <span>本文</span>
                  <textarea
                    value={active.body}
                    rows={8}
                    onChange={(event) => updateActive({ body: event.target.value })}
                  />
                </label>
                <div className="field-row">
                  <label className="field">
                    <span>レイアウト</span>
                    <select
                      value={active.layout}
                      onChange={(event) => updateActive({ layout: event.target.value as SlideLayout })}
                    >
                      {SLIDE_LAYOUTS.map((layout) => (
                        <option key={layout} value={layout}>
                          {LAYOUT_LABELS[layout]}
                        </option>
                      ))}
                    </select>
                  </label>
                  <div className="field">
                    <span>背景色</span>
                    <div className="swatch-row">
                      {SLIDE_BACKGROUNDS.map((color) => (
                        <button
                          key={color}
                          type="button"
                          className={`swatch${active.background === color ? ' is-selected' : ''}`}
                          style={{ backgroundColor: color }}
                          title={color}
                          onClick={() => updateActive({ background: color })}
                        />
                      ))}
                    </div>
                    {selectedElementId ? (
                      <label className="field">
                        <span>選択要素のテキスト</span>
                        <input
                          type="text"
                          value={(active.elements ?? []).find((element) => element.id === selectedElementId)?.text ?? ''}
                          onChange={(event) => updateElement(selectedElementId, { text: event.target.value })}
                        />
                      </label>
                    ) : null}
                  </div>
                </div>
              </div>
            ) : null}
          </section>
        </div>

        <div className="slide-footer">
          <button
            type="button"
            className="tb-button"
            disabled={activeIndex <= 0}
            onClick={() => setActive(activeIndex - 1)}
          >
            ◀ 前のスライド
          </button>
          <span className="slide-counter">
            {slides.length ? activeIndex + 1 : 0} / {slides.length}
          </span>
          <button
            type="button"
            className="tb-button"
            disabled={activeIndex >= slides.length - 1}
            onClick={() => setActive(activeIndex + 1)}
          >
            次のスライド ▶
          </button>
          <button type="button" className="tb-button primary" onClick={() => setPresenting(true)}>
            Present
          </button>
        </div>

        {presenting ? (
          <PresentationOverlay
            slides={slides}
            startIndex={activeIndex}
            onClose={() => setPresenting(false)}
          />
        ) : null}
      </div>
    );
  },
);

export default PresentationEditor;
