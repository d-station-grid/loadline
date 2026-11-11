import { Component, type ReactNode } from "react";

type Props = { children: ReactNode };
type State = { failed: boolean };

/**
 * アバターの部分で起きたエラーを、ここで止める。three.js のファイルを取れなかった
 * （lazy の読み込みの失敗。Suspense は受け止めない）ときや、描画中に例外が出たときに、
 * ダッシュボードごと外れないようにする。アバターだけを出さず、字幕と声は使える
 */
export default class AvatarBoundary extends Component<Props, State> {
  state: State = { failed: false };

  static getDerivedStateFromError(): State {
    return { failed: true };
  }

  render() {
    return this.state.failed ? null : this.props.children;
  }
}
