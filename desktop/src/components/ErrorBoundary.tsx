import { Component, type ErrorInfo, type ReactNode } from "react";

interface Props {
  children: ReactNode;
  label: string;
}

/** Keeps one broken panel from blanking the whole Command Center. */
export class ErrorBoundary extends Component<Props, { error: Error | null }> {
  state = { error: null as Error | null };

  static getDerivedStateFromError(error: Error) {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error(`[${this.props.label}]`, error, info.componentStack);
  }

  render() {
    if (!this.state.error) return this.props.children;
    return (
      <div className="flex flex-col items-center gap-2 p-4 text-center text-sm text-red-200" role="alert">
        <span>{this.props.label} dikhate waqt masla aa gaya.</span>
        <span className="font-mono text-xs text-red-300/70">{this.state.error.message}</span>
        <button
          type="button"
          onClick={() => this.setState({ error: null })}
          className="rounded-lg border border-red-400/40 px-3 py-1 text-xs hover:bg-red-500/10"
        >
          Dobara koshish karein
        </button>
      </div>
    );
  }
}
