import { act, render } from "@testing-library/react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";

import AvatarStage from "./AvatarStage";

// jsdom には WebGL がないので、three.js とモデルの読み込みを差し替える。
// 描画のループ、監視、renderer の片づけが呼ばれたかを見る
const gl = vi.hoisted(() => ({
  renderers: [] as { dispose: () => void; render: () => void }[],
  loads: [] as {
    onLoad: (gltf: unknown) => void;
    onError: (e: unknown) => void;
  }[],
  observers: [] as { disconnect: () => void }[],
}));

vi.mock("three", () => {
  class Vec {
    set() {}
  }
  class WebGLRenderer {
    domElement = document.createElement("canvas");
    dispose = vi.fn();
    render = vi.fn();
    setPixelRatio() {}
    setSize() {}
    constructor() {
      gl.renderers.push(this);
    }
  }
  class Scene {
    add() {}
  }
  class PerspectiveCamera {
    position = new Vec();
    aspect = 1;
    lookAt() {}
    updateProjectionMatrix() {}
  }
  class AmbientLight {}
  class DirectionalLight {
    position = new Vec();
  }
  class Timer {
    connect() {}
    update() {}
    reset() {}
    dispose = vi.fn();
    getDelta() {
      return 1 / 60;
    }
    getElapsed() {
      return 0;
    }
  }
  return {
    WebGLRenderer,
    Scene,
    PerspectiveCamera,
    AmbientLight,
    DirectionalLight,
    Timer,
  };
});

vi.mock("three/addons/loaders/GLTFLoader.js", () => ({
  GLTFLoader: class {
    register() {}
    load(
      _url: string,
      onLoad: (gltf: unknown) => void,
      _onProgress: unknown,
      onError: (e: unknown) => void,
    ) {
      gl.loads.push({ onLoad, onError });
    }
  },
}));

vi.mock("@pixiv/three-vrm", () => ({
  VRMLoaderPlugin: class {},
  VRMUtils: {
    deepDispose: vi.fn(),
    removeUnnecessaryVertices: vi.fn(),
    combineSkeletons: vi.fn(),
    rotateVRM0: vi.fn(),
  },
}));

// 描画のループは手で 1 フレームずつ進める
let frames = new Map<number, FrameRequestCallback>();
let nextFrame = 1;

function runFrame() {
  const pending = frames;
  frames = new Map();
  for (const callback of pending.values()) callback(performance.now());
}

beforeEach(() => {
  gl.renderers.length = 0;
  gl.loads.length = 0;
  gl.observers.length = 0;
  frames = new Map();
  vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockReturnValue(
    {} as RenderingContext,
  );
  vi.stubGlobal("requestAnimationFrame", (callback: FrameRequestCallback) => {
    const id = nextFrame++;
    frames.set(id, callback);
    return id;
  });
  vi.stubGlobal("cancelAnimationFrame", (id: number) => {
    frames.delete(id);
  });
  vi.stubGlobal(
    "ResizeObserver",
    class {
      disconnect = vi.fn();
      observe() {}
      constructor() {
        gl.observers.push(this);
      }
    },
  );
});

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

function expectCleanedUp() {
  expect(frames.size).toBe(0);
  expect(gl.renderers[0].dispose).toHaveBeenCalledTimes(1);
  expect(gl.observers[0].disconnect).toHaveBeenCalledTimes(1);
}

test("見えているあいだは、毎フレーム描く", () => {
  render(<AvatarStage expression="happy" speaking={false} />);

  runFrame();
  runFrame();

  expect(gl.renderers[0].render).toHaveBeenCalledTimes(2);
  expect(frames.size).toBe(1);
});

test("モデルを読めなければ、描画を止めて片づけ、何も出さない", () => {
  const { container } = render(
    <AvatarStage expression="happy" speaking={false} />,
  );
  runFrame();

  act(() => gl.loads[0].onError(new Error("404")));

  expectCleanedUp();
  expect(container).toBeEmptyDOMElement();
});

test("読めたものが VRM でなければ、同じく止めて片づける", () => {
  const { container } = render(
    <AvatarStage expression="happy" speaking={false} />,
  );

  act(() => gl.loads[0].onLoad({ userData: {}, scene: {} }));

  expectCleanedUp();
  expect(container).toBeEmptyDOMElement();
});

test("失敗して片づけたあとに外れても、二重に片づけない", () => {
  const { unmount } = render(
    <AvatarStage expression="happy" speaking={false} />,
  );
  act(() => gl.loads[0].onError(new Error("404")));

  unmount();

  expectCleanedUp();
});

test("隠しているあいだは描かず、見せたら描き直す", () => {
  const { rerender } = render(
    <AvatarStage expression="happy" speaking={false} visible={false} />,
  );
  expect(frames.size).toBe(0);

  rerender(<AvatarStage expression="happy" speaking={false} visible />);
  runFrame();
  expect(gl.renderers[0].render).toHaveBeenCalledTimes(1);

  rerender(<AvatarStage expression="happy" speaking={false} visible={false} />);
  expect(frames.size).toBe(0);
  // 隠しても片づけはしない（出し直すときにモデルを読み直さない）
  expect(gl.renderers[0].dispose).not.toHaveBeenCalled();
  expect(gl.loads).toHaveLength(1);
});

test("外れたら、描画を止めて片づける", () => {
  const { unmount } = render(
    <AvatarStage expression="happy" speaking={false} />,
  );
  runFrame();

  unmount();

  expectCleanedUp();
});

/** 読めた VRM の代わり。表情に入れた値を覚える */
function loadFakeVrm() {
  const values = new Map<string, number>();
  const vrm = {
    scene: { traverse() {} },
    humanoid: { getNormalizedBoneNode: () => null },
    expressionManager: {
      setValue: (name: string, value: number) => values.set(name, value),
    },
    lookAt: null,
    update() {},
  };
  act(() => gl.loads[0].onLoad({ userData: { vrm }, scene: {} }));
  return values;
}

test("話しているあいだは、声の大きさに合わせて口を開く", () => {
  const level = vi.fn(() => 1);
  render(<AvatarStage expression="relaxed" speaking voiceLevel={level} />);
  const values = loadFakeVrm();

  runFrame();

  expect(level).toHaveBeenCalled();
  expect(values.get("aa")).toBeGreaterThan(0.3);
});

test("話していないときは声を読まず、口は閉じたまま", () => {
  const level = vi.fn(() => 1);
  render(
    <AvatarStage expression="relaxed" speaking={false} voiceLevel={level} />,
  );
  const values = loadFakeVrm();

  runFrame();

  expect(level).not.toHaveBeenCalled();
  expect(values.get("aa")).toBe(0);
});

test("話し終えたら、口を閉じていく", () => {
  const { rerender } = render(
    <AvatarStage expression="relaxed" speaking voiceLevel={() => 1} />,
  );
  const values = loadFakeVrm();
  runFrame();
  const open = values.get("aa") ?? 0;

  rerender(
    <AvatarStage expression="relaxed" speaking={false} voiceLevel={() => 1} />,
  );
  runFrame();

  expect(values.get("aa")).toBeLessThan(open);
});
