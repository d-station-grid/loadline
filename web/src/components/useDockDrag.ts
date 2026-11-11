import {
  type PointerEvent as ReactPointerEvent,
  type RefObject,
  useEffect,
  useRef,
  useState,
} from "react";

/** 右下の置き場所からのずれ（px）。右と下が正 */
export type Offset = { x: number; y: number };

/** ずれがないときの、浮かせた部品の位置（画面の左上からの px） */
type Bounds = { left: number; top: number; right: number; bottom: number };

/**
 * ずれを、部品が画面からはみ出さない範囲に収める。画面より大きいときは、
 * 左上を画面に残す（吹き出しの上の段に、再生ボタンと Hide がある）
 */
export function clampOffset(
  offset: Offset,
  base: Bounds,
  viewport: { width: number; height: number },
): Offset {
  const clamp = (v: number, min: number, max: number) =>
    Math.max(min, Math.min(v, max));
  return {
    x: clamp(offset.x, -base.left, viewport.width - base.right),
    y: clamp(offset.y, -base.top, viewport.height - base.bottom),
  };
}

function viewport() {
  return { width: window.innerWidth, height: window.innerHeight };
}

/** 今の位置から、ずれを引いた位置 */
function baseOf(element: HTMLElement, offset: Offset): Bounds {
  const r = element.getBoundingClientRect();
  return {
    left: r.left - offset.x,
    top: r.top - offset.y,
    right: r.right - offset.x,
    bottom: r.bottom - offset.y,
  };
}

/**
 * 画面に浮かせた部品を、つかんで動かす。返すずれを transform で当て、
 * handlers をつかむところに付ける。マウスでも指でも動かせる。
 * 画面の大きさや部品の大きさが変わったら、はみ出さないよう収め直す
 */
export function useDockDrag(target: RefObject<HTMLElement | null>) {
  const [offset, setOffset] = useState<Offset>({ x: 0, y: 0 });
  // 収め直しは描画の外で走るので、今のずれを ref でも持つ
  const current = useRef(offset);
  useEffect(() => {
    current.current = offset;
  }, [offset]);
  const drag = useRef<{
    pointer: number;
    startX: number;
    startY: number;
    from: Offset;
    base: Bounds;
  } | null>(null);

  useEffect(() => {
    const element = target.current;
    if (!element) return;
    function refit() {
      if (!element || drag.current) return;
      const from = current.current;
      // 隠れているとき（大きさが 0）は収め直さない
      const r = element.getBoundingClientRect();
      if (r.width === 0 && r.height === 0) return;
      const next = clampOffset(from, baseOf(element, from), viewport());
      if (next.x !== from.x || next.y !== from.y) setOffset(next);
    }
    window.addEventListener("resize", refit);
    const observer =
      typeof ResizeObserver === "undefined" ? null : new ResizeObserver(refit);
    observer?.observe(element);
    return () => {
      window.removeEventListener("resize", refit);
      observer?.disconnect();
    };
  }, [target]);

  const handlers = {
    onPointerDown(e: ReactPointerEvent<HTMLElement>) {
      // マウスは左ボタンだけ。指とペンは button が 0
      if (e.button !== 0) return;
      const element = target.current;
      if (!element) return;
      drag.current = {
        pointer: e.pointerId,
        startX: e.clientX,
        startY: e.clientY,
        from: current.current,
        base: baseOf(element, current.current),
      };
      // 指を部品の外へ動かしても追えるよう、つかんだまま離さない
      e.currentTarget.setPointerCapture?.(e.pointerId);
      // 文字の選択を始めない
      e.preventDefault();
    },
    onPointerMove(e: ReactPointerEvent<HTMLElement>) {
      const d = drag.current;
      if (!d || d.pointer !== e.pointerId) return;
      const next = clampOffset(
        {
          x: d.from.x + e.clientX - d.startX,
          y: d.from.y + e.clientY - d.startY,
        },
        d.base,
        viewport(),
      );
      current.current = next;
      setOffset(next);
    },
    onPointerUp(e: ReactPointerEvent<HTMLElement>) {
      if (drag.current?.pointer === e.pointerId) drag.current = null;
    },
    onPointerCancel(e: ReactPointerEvent<HTMLElement>) {
      if (drag.current?.pointer === e.pointerId) drag.current = null;
    },
  };

  return { offset, handlers };
}
