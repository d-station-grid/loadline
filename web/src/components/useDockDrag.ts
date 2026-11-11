import {
  type MouseEvent as ReactMouseEvent,
  type PointerEvent as ReactPointerEvent,
  type RefObject,
  useEffect,
  useRef,
  useState,
} from "react";

/**
 * これより動いたら、押したのではなく動かしたとみなす（px）。ボタンをつかんだときに、
 * 手のぶれで押せなくならないようにする。指は、ブラウザが click を出す範囲が広い
 * （Chrome は 15 px 動いても click を出す）ので、それより広く取る
 */
const DRAG_THRESHOLD = { mouse: 4, touch: 16 };

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

/**
 * スマートフォンの並び（index.css の @media と同じ幅）では、上下にだけ動かす。
 * 吹き出しが画面の幅いっぱいなので、左右に動かす余地がない
 */
const NARROW = "(max-width: 640px)";

function verticalOnly(): boolean {
  return (
    typeof window.matchMedia === "function" && window.matchMedia(NARROW).matches
  );
}

/** 画面に収めたずれ。上下にだけ動かす幅では、左右は右下の置き場所のまま */
function place(offset: Offset, base: Bounds): Offset {
  const next = clampOffset(offset, base, viewport());
  return verticalOnly() ? { x: 0, y: next.y } : next;
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
 * 今の位置から測り直して、画面に収めたずれ。隠れているとき（大きさが 0）は null
 */
function fitted(element: HTMLElement, from: Offset): Offset | null {
  const r = element.getBoundingClientRect();
  if (r.width === 0 && r.height === 0) return null;
  return place(from, baseOf(element, from));
}

/**
 * 画面に浮かせた部品を、つかんで動かす。返すずれを transform で当て、
 * handlers をつかむところに付ける。マウスでも指でも動かせる。
 * 画面の大きさや部品の大きさが変わったら、はみ出さないよう収め直す。
 * スマートフォンの幅では上下にだけ動かし、幅が変わってそうなったら左右を戻す。
 * ボタンにも付けられる。動かしたあとに離しても、押したことにはしない
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
    moved: boolean;
    threshold: number;
  } | null>(null);
  // 動かし終えた直後の click を 1 回だけ止める（ボタンを開かない）
  const swallowClick = useRef(false);

  useEffect(() => {
    const element = target.current;
    if (!element) return;
    function refit() {
      // 動かしているあいだは、離したときにまとめて収める
      if (!element || drag.current) return;
      const from = current.current;
      const next = fitted(element, from);
      if (next && (next.x !== from.x || next.y !== from.y)) setOffset(next);
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

  /**
   * 離したとき。動かしているあいだに画面の大きさが変わっていたら、つかんだときに
   * 測った位置は古いので、今の位置から測り直して画面に収める
   */
  function release(pointer: number) {
    if (drag.current?.pointer !== pointer) return;
    swallowClick.current = drag.current.moved;
    drag.current = null;
    const element = target.current;
    if (!element) return;
    const from = current.current;
    const next = fitted(element, from);
    if (next && (next.x !== from.x || next.y !== from.y)) {
      current.current = next;
      setOffset(next);
    }
  }

  const handlers = {
    onPointerDown(e: ReactPointerEvent<HTMLElement>) {
      // マウスは左ボタンだけ。指とペンは button が 0
      if (e.button !== 0) return;
      const element = target.current;
      if (!element) return;
      swallowClick.current = false;
      drag.current = {
        pointer: e.pointerId,
        startX: e.clientX,
        startY: e.clientY,
        from: current.current,
        base: baseOf(element, current.current),
        moved: false,
        threshold:
          e.pointerType === "touch"
            ? DRAG_THRESHOLD.touch
            : DRAG_THRESHOLD.mouse,
      };
      // 指を部品の外へ動かしても追えるよう、つかんだまま離さない
      e.currentTarget.setPointerCapture?.(e.pointerId);
      // マウスでは文字の選択を始めない。指では呼ばない。ブラウザによっては、
      // 動かさずにタップしても click が出なくなる（指の選択は CSS の user-select で止める）
      if (e.pointerType !== "touch") e.preventDefault();
    },
    onPointerMove(e: ReactPointerEvent<HTMLElement>) {
      const d = drag.current;
      if (!d || d.pointer !== e.pointerId) return;
      if (!d.moved) {
        const dy = e.clientY - d.startY;
        // 上下にだけ動かす幅では、左右の動きは数えない
        const dx = verticalOnly() ? 0 : e.clientX - d.startX;
        const distance = Math.hypot(dx, dy);
        if (distance < d.threshold) return;
        d.moved = true;
      }
      const next = place(
        {
          x: d.from.x + e.clientX - d.startX,
          y: d.from.y + e.clientY - d.startY,
        },
        d.base,
      );
      current.current = next;
      setOffset(next);
    },
    onPointerUp(e: ReactPointerEvent<HTMLElement>) {
      release(e.pointerId);
    },
    onPointerCancel(e: ReactPointerEvent<HTMLElement>) {
      release(e.pointerId);
    },
    onClickCapture(e: ReactMouseEvent<HTMLElement>) {
      // キーボードで押したとき（detail が 0）は止めない。指で動かしたあとは click が
      // 来ないことがあり、止める印が残っていても、キーボードでは開けるようにする
      if (!swallowClick.current || e.detail === 0) return;
      swallowClick.current = false;
      e.preventDefault();
      e.stopPropagation();
    },
  };

  return { offset, handlers };
}
