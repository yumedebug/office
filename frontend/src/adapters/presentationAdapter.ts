import type { OperationResult, PresentationHandle, SlideData } from '../types';
import { createSlide, ensureSlides } from '../utils/converters';

export interface PresentationAdapter {
  getData(): SlideData[];
  setData(slides: SlideData[]): void;
  insertText(text: string): OperationResult;
  appendSlides(slides: SlideData[]): OperationResult;
  getActiveIndex(): number;
  setActiveIndex(index: number): void;
}

export function createPresentationAdapter(
  getHandle: () => PresentationHandle | null,
): PresentationAdapter {
  const readSlides = (): SlideData[] => getHandle()?.getSlides() ?? [];

  return {
    getData: () => readSlides(),

    setData: (slides) => {
      getHandle()?.setSlides(ensureSlides(slides));
    },

    insertText: (text) => {
      const handle = getHandle();
      if (!handle) {
        return { ok: false, error: 'スライドエディタが初期化されていません。' };
      }
      const slides = readSlides();
      if (slides.length === 0) {
        handle.setSlides([createSlide({ title: 'AI Response', body: text, layout: 'title-content' })]);
        handle.setActiveIndex(0);
        return { ok: true, message: '最初のスライドを作成しました' };
      }
      const index = Math.min(Math.max(handle.getActiveIndex(), 0), slides.length - 1);
      const current = slides[index];
      const body = current.body.trim() ? `${current.body}\n${text}` : text;
      const updated = slides.map((slide, position) =>
        position === index
          ? {
              ...slide,
              body,
              layout: slide.layout === 'title-only' ? ('title-content' as const) : slide.layout,
            }
          : slide,
      );
      handle.setSlides(updated);
      return { ok: true, message: `スライド ${index + 1} の本文に挿入しました` };
    },

    appendSlides: (slides) => {
      const handle = getHandle();
      if (!handle) {
        return { ok: false, error: 'スライドエディタが初期化されていません。' };
      }
      const incoming = ensureSlides(slides);
      if (!incoming.length) {
        return { ok: false, error: '追加するスライドがありません。' };
      }
      const combined = [...readSlides(), ...incoming];
      handle.setSlides(combined);
      handle.setActiveIndex(combined.length - incoming.length);
      return { ok: true, message: `${incoming.length} 枚のスライドを追加しました` };
    },

    getActiveIndex: () => getHandle()?.getActiveIndex() ?? 0,

    setActiveIndex: (index) => {
      getHandle()?.setActiveIndex(index);
    },
  };
}
