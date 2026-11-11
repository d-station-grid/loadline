import { VRMLoaderPlugin, VRMUtils, type VRM } from "@pixiv/three-vrm";
import { useEffect, useRef, useState } from "react";
import * as THREE from "three";
import { GLTFLoader } from "three/addons/loaders/GLTFLoader.js";

import type { Expression } from "../../api";
import {
  blinkWeight,
  BLINK_SECONDS,
  EXPRESSIONS,
  faceTarget,
  nextBlinkDelay,
} from "./face";

/**
 * MVP はサンプルのモデル（pixiv の VRM1_Constraint_Twist_Sample）を使う。利用条件は
 * モデルの中にあり、法人の商用利用・再配布・改変ができ、クレジットの表記は要らない
 */
const MODEL_URL = "/models/sample.vrm";

/** カメラ。height は見る高さ（m）、distance はモデルからの距離（m）、fov は縦の画角（度） */
const CAMERA = { fov: 28, height: 0.82, distance: 3.7 };

/** 表情を切り替える速さ。1 フレームで目標との差のこの割合だけ近づける */
const FACE_EASING = 0.08;

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
};

/**
 * 振り返りを話すアバター。three-vrm で VRM を描き、まばたき、呼吸と首の揺れ、
 * 表情の切り替えをする。字幕は別に出すので、読み上げソフトには見せない。
 * WebGL が使えない、モデルを読めない、のときは何も出さない（字幕と声だけで成り立つ）
 */
export default function AvatarStage({ expression, speaking }: Props) {
  const mountRef = useRef<HTMLDivElement>(null);
  // 描画のループからは props を直接見られないので、ref で渡す
  const face = useRef(faceTarget(expression, speaking));
  useEffect(() => {
    face.current = faceTarget(expression, speaking);
  }, [expression, speaking]);
  const [failed, setFailed] = useState(() => !canUseWebGL());

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

    let disposed = false;
    let vrm: VRM | null = null;
    const loader = new GLTFLoader();
    loader.register((parser) => new VRMLoaderPlugin(parser));
    loader.load(
      MODEL_URL,
      (gltf) => {
        const loaded = gltf.userData.vrm as VRM;
        if (disposed) {
          VRMUtils.deepDispose(loaded.scene);
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
        if (!disposed) setFailed(true);
      },
    );

    const timer = new THREE.Timer();
    // タブを隠して戻ったときに、止まっていた時間ぶん動きが飛ばないようにする
    timer.connect(document);
    let nextBlinkAt = nextBlinkDelay(Math.random());
    let blinkStartedAt = -1;
    const weights: Record<Expression, number> = {
      happy: 0,
      relaxed: 0,
      sad: 0,
      surprised: 0,
    };

    let frame = 0;
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
        if (head) {
          head.rotation.y = Math.sin(t * 0.5) * 0.05;
          head.rotation.z = Math.sin(t * 0.37) * 0.02;
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

          // 表情はなめらかに切り替える
          for (const e of EXPRESSIONS) {
            weights[e] += (face.current[e] - weights[e]) * FACE_EASING;
            em.setValue(e, weights[e]);
          }
        }

        vrm.update(delta);
      }

      renderer.render(scene, camera);
    };
    frame = requestAnimationFrame(tick);

    // 画面の幅に合わせて描き直す。並びが変わると、窓の大きさが同じでも枠が変わる
    const observer = new ResizeObserver(() => {
      const width = mount.clientWidth;
      const height = Math.max(mount.clientHeight, 1);
      camera.aspect = width / height;
      camera.updateProjectionMatrix();
      renderer.setSize(width, height);
    });
    observer.observe(mount);

    return () => {
      disposed = true;
      cancelAnimationFrame(frame);
      observer.disconnect();
      if (vrm) VRMUtils.deepDispose(vrm.scene);
      timer.dispose();
      renderer.dispose();
      mount.removeChild(renderer.domElement);
    };
  }, []);

  if (failed) return null;
  return <div ref={mountRef} className="avatar-stage" aria-hidden="true" />;
}
