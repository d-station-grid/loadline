import { VRMLoaderPlugin, VRMUtils, type VRM } from "@pixiv/three-vrm";
import { useEffect, useRef, useState } from "react";
import * as THREE from "three";
import { GLTFLoader } from "three/addons/loaders/GLTFLoader.js";

import type { Expression } from "../../api";
import {
  blinkWeight,
  BLINK_SECONDS,
  EXPRESSIONS,
  faceEasing,
  faceTarget,
  nextBlinkDelay,
  nextMouth,
} from "./face";

/**
 * MVP はサンプルのモデル（pixiv の VRM1_Constraint_Twist_Sample）を使う。利用条件は
 * モデルの中にあり、法人の商用利用・再配布・改変ができ、クレジットの表記は要らない
 */
const MODEL_URL = "/models/sample.vrm";

/** カメラ。height は見る高さ（m）、distance はモデルからの距離（m）、fov は縦の画角（度） */
const CAMERA = { fov: 28, height: 0.82, distance: 3.7 };

/** WebGL2 が使えるか。three.js は WebGL2 だけに対応する */
function canUseWebGL(): boolean {
  try {
    return document.createElement("canvas").getContext("webgl2") !== null;
  } catch {
    return false;
  }
}

type Props = {
  /** 振り返りの表情。話す前と話し終えたあとに出す */
  expression: Expression;
  /** 声を再生しているあいだ true。表情を relaxed にそろえる */
  speaking: boolean;
  /**
   * false のあいだは描画を止める。畳んだときに外さずに隠すためのもの。
   * 外すと、出し直すたびにモデルを読み直すことになる
   */
  visible?: boolean;
  /**
   * 今の声の大きさ（0〜1）。毎フレーム読み、口の開きにする。話していないときは読まない
   */
  voiceLevel?: () => number;
};

/**
 * 振り返りを話すアバター。three-vrm で VRM を描き、まばたき、呼吸と首の揺れ、
 * 表情の切り替えをする。字幕は別に出すので、読み上げソフトには見せない。
 * WebGL が使えない、モデルを読めない、のときは描画を片づけて何も出さない
 * （字幕と声だけで成り立つ）
 */
export default function AvatarStage({
  expression,
  speaking,
  visible = true,
  voiceLevel,
}: Props) {
  const mountRef = useRef<HTMLDivElement>(null);
  // 描画のループからは props を直接見られないので、ref で渡す
  const face = useRef(faceTarget(expression, speaking));
  // 口は話しているあいだだけ、声の大きさに合わせて動かす
  const voice = useRef<(() => number) | null>(null);
  useEffect(() => {
    face.current = faceTarget(expression, speaking);
    voice.current = speaking && voiceLevel ? voiceLevel : null;
  }, [expression, speaking, voiceLevel]);
  const [failed, setFailed] = useState(() => !canUseWebGL());
  // 描画のループを止めたり動かしたりする。下の effect が用意する
  const loop = useRef<{ start: () => void; stop: () => void } | null>(null);

  useEffect(() => {
    const mount = mountRef.current;
    if (!mount) return;

    let renderer: THREE.WebGLRenderer;
    try {
      renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
    } catch {
      // 確かめたあとで作れなかったとき。枠は空のまま残る
      return;
    }
    // 高精細な画面のスマートフォンで重くならないよう、2 倍までにする
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    renderer.setSize(mount.clientWidth, mount.clientHeight);
    mount.appendChild(renderer.domElement);

    const scene = new THREE.Scene();
    // 全身が縦長の枠に収まる位置（Figma は 150×280 で、右下に立たせる）。
    // モデルを替えたら合わせ直す
    const camera = new THREE.PerspectiveCamera(
      CAMERA.fov,
      mount.clientWidth / Math.max(mount.clientHeight, 1),
      0.1,
      20,
    );
    camera.position.set(0, CAMERA.height, CAMERA.distance);
    camera.lookAt(0, CAMERA.height, 0);

    scene.add(new THREE.AmbientLight(0xffffff, 1.6));
    const light = new THREE.DirectionalLight(0xffffff, 1.8);
    light.position.set(1, 2, 2);
    scene.add(light);

    const timer = new THREE.Timer();
    // タブを隠して戻ったときに、止まっていた時間ぶん動きが飛ばないようにする
    timer.connect(document);

    // 画面の幅に合わせて描き直す。並びが変わると、窓の大きさが同じでも枠が変わる。
    // 隠しているあいだは大きさが 0 になるので、そのときは変えない
    const observer = new ResizeObserver(() => {
      const width = mount.clientWidth;
      const height = mount.clientHeight;
      if (width === 0 || height === 0) return;
      camera.aspect = width / height;
      camera.updateProjectionMatrix();
      renderer.setSize(width, height);
    });
    observer.observe(mount);

    let vrm: VRM | null = null;
    let frame = 0;
    let disposed = false;

    /**
     * 描画を片づける。読み込みに失敗したときと、外れるときに呼ぶ。2 回呼んでもよい。
     * 失敗したときは部品が残るので、外れるのを待たずにここで止める
     */
    function dispose() {
      if (disposed) return;
      disposed = true;
      cancelAnimationFrame(frame);
      observer.disconnect();
      if (vrm) VRMUtils.deepDispose(vrm.scene);
      vrm = null;
      timer.dispose();
      renderer.dispose();
      renderer.domElement.remove();
    }

    function fail() {
      dispose();
      setFailed(true);
    }

    const loader = new GLTFLoader();
    loader.register((parser) => new VRMLoaderPlugin(parser));
    loader.load(
      MODEL_URL,
      (gltf) => {
        const loaded = gltf.userData.vrm as VRM | undefined;
        if (disposed) {
          if (loaded) VRMUtils.deepDispose(loaded.scene);
          return;
        }
        // glTF としては読めても VRM でなければ、失敗として止める
        if (!loaded) {
          fail();
          return;
        }
        VRMUtils.removeUnnecessaryVertices(gltf.scene);
        VRMUtils.combineSkeletons(gltf.scene);
        VRMUtils.rotateVRM0(loaded);
        loaded.scene.traverse((obj) => {
          obj.frustumCulled = false;
        });
        // 視線はカメラ（見ている人）に向ける
        if (loaded.lookAt) loaded.lookAt.target = camera;
        scene.add(loaded.scene);
        vrm = loaded;
      },
      undefined,
      () => {
        if (!disposed) fail();
      },
    );

    let mouth = 0;
    let nextBlinkAt = nextBlinkDelay(Math.random());
    let blinkStartedAt = -1;
    const weights: Record<Expression, number> = {
      happy: 0,
      relaxed: 0,
      sad: 0,
      surprised: 0,
    };

    const tick = (now: number) => {
      frame = requestAnimationFrame(tick);
      timer.update(now);
      const delta = timer.getDelta();
      const t = timer.getElapsed();

      if (vrm) {
        const bone = vrm.humanoid.getNormalizedBoneNode.bind(vrm.humanoid);

        // T ポーズから腕を下ろす
        const leftArm = bone("leftUpperArm");
        const rightArm = bone("rightUpperArm");
        if (leftArm) leftArm.rotation.z = -1.25 + Math.sin(t * 0.9) * 0.015;
        if (rightArm) rightArm.rotation.z = 1.25 - Math.sin(t * 0.9) * 0.015;

        // 呼吸と、わずかな首の揺れ
        const chest = bone("chest") ?? bone("spine");
        if (chest) chest.rotation.x = Math.sin(t * 1.4) * 0.012;
        const head = bone("head");
        // 口は声の大きさへ寄せる。話し終えたら閉じる
        mouth = nextMouth(mouth, voice.current?.() ?? 0, delta);
        if (head) {
          head.rotation.y = Math.sin(t * 0.5) * 0.05;
          head.rotation.z = Math.sin(t * 0.37) * 0.02;
          // 話している間は、口の開きに合わせて少しうなずく
          head.rotation.x = mouth * 0.05;
        }

        const em = vrm.expressionManager;
        if (em) {
          if (blinkStartedAt < 0 && t > nextBlinkAt) blinkStartedAt = t;
          if (blinkStartedAt >= 0) {
            em.setValue("blink", blinkWeight(t - blinkStartedAt));
            if (t - blinkStartedAt >= BLINK_SECONDS) {
              blinkStartedAt = -1;
              nextBlinkAt = t + nextBlinkDelay(Math.random());
            }
          }

          em.setValue("aa", mouth);

          // 表情はなめらかに切り替える。速さは画面の書き換えの回数によらない
          const easing = faceEasing(delta);
          for (const e of EXPRESSIONS) {
            weights[e] += (face.current[e] - weights[e]) * easing;
            em.setValue(e, weights[e]);
          }
        }

        vrm.update(delta);
      }

      renderer.render(scene, camera);
    };

    let running = false;
    loop.current = {
      start() {
        if (disposed || running) return;
        running = true;
        // 止めていたあいだの時間を、動きに入れない
        timer.reset();
        frame = requestAnimationFrame(tick);
      },
      stop() {
        running = false;
        cancelAnimationFrame(frame);
      },
    };

    return () => {
      loop.current = null;
      dispose();
    };
  }, []);

  // 見えているあいだだけ描く。effect は宣言の順に走るので、ループの用意のあとになる
  useEffect(() => {
    if (visible) loop.current?.start();
    else loop.current?.stop();
  }, [visible]);

  if (failed) return null;
  return <div ref={mountRef} className="avatar-stage" aria-hidden="true" />;
}
