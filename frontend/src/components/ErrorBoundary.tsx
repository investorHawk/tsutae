import { Component, type ErrorInfo, type ReactNode } from "react";

interface ErrorBoundaryProps {
  /** 描画中に例外が出たときに代わりに出すもの（患者画面は t("error.generic")） */
  fallback: ReactNode;
  /** 変わったら失敗の表示を解いて children を描き直す（経路を渡す） */
  resetKey?: string;
  children: ReactNode;
}

interface ErrorBoundaryState {
  failed: boolean;
}

/**
 * 描画中の例外で画面が真っ白にならないようにする（docs/architecture.md §9 W2b の決定）。
 * 例外の中身は画面にも console にも出さない（記録の文面が入りうるため。React 自身の
 * 開発時の出力は除く）。
 */
export default class ErrorBoundary extends Component<
  ErrorBoundaryProps,
  ErrorBoundaryState
> {
  state: ErrorBoundaryState = { failed: false };

  static getDerivedStateFromError(): ErrorBoundaryState {
    return { failed: true };
  }

  componentDidCatch(_error: unknown, _info: ErrorInfo): void {
    // 何も残さない（上の注記）
  }

  componentDidUpdate(prev: ErrorBoundaryProps): void {
    if (this.state.failed && prev.resetKey !== this.props.resetKey) {
      this.setState({ failed: false });
    }
  }

  render(): ReactNode {
    return this.state.failed ? this.props.fallback : this.props.children;
  }
}
