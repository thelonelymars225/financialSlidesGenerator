import { Component, type ErrorInfo, type ReactNode } from "react";

interface ApplicationErrorBoundaryProps {
  children: ReactNode;
}

interface ApplicationErrorBoundaryState {
  error: Error | null;
}

function errorRequestId(error: Error): string | undefined {
  const requestId = (error as Error & { requestId?: unknown }).requestId;
  return typeof requestId === "string" && requestId ? requestId : undefined;
}

export function logRenderingError(error: Error, development = import.meta.env.DEV): void {
  const metadata = {
    errorName: error.name || "Error",
    requestId: errorRequestId(error) ?? "unavailable",
  };
  if (development) {
    console.error("Application render failure", { ...metadata, stack: error.stack });
    return;
  }
  console.error("Application render failure", metadata);
}

interface RecoveryScreenProps {
  onReset: () => void;
  onReload: () => void;
}

export function RecoveryScreen({ onReset, onReload }: RecoveryScreenProps) {
  return (
    <main className="grid min-h-screen place-items-center bg-stone-100 px-4 text-emerald-950 dark:bg-[#0b1210] dark:text-stone-100">
      <section className="w-full max-w-md rounded-3xl border border-stone-200 bg-white p-8 text-center shadow-xl dark:border-white/10 dark:bg-white/[0.045]">
        <h1 className="text-2xl font-bold">Something went wrong</h1>
        <p className="mt-3 text-stone-600 dark:text-stone-300">
          The application hit an unexpected problem. Your source has not been resubmitted.
        </p>
        <div className="mt-6 flex flex-col gap-3 sm:flex-row sm:justify-center">
          <button className="rounded-xl bg-emerald-950 px-5 py-3 font-semibold text-white dark:bg-emerald-200 dark:text-emerald-950" type="button" onClick={onReset}>
            Try again
          </button>
          <button className="rounded-xl border border-stone-300 px-5 py-3 font-semibold dark:border-white/20" type="button" onClick={onReload}>
            Reload application
          </button>
        </div>
      </section>
    </main>
  );
}

export class ApplicationErrorBoundary extends Component<
  ApplicationErrorBoundaryProps,
  ApplicationErrorBoundaryState
> {
  state: ApplicationErrorBoundaryState = { error: null };

  static getDerivedStateFromError(error: Error): ApplicationErrorBoundaryState {
    return { error };
  }

  componentDidCatch(error: Error, _errorInfo: ErrorInfo): void {
    logRenderingError(error);
  }

  private reset = () => {
    this.setState({ error: null });
  };

  render() {
    if (this.state.error) {
      return (
        <RecoveryScreen
          onReset={this.reset}
          onReload={() => window.location.reload()}
        />
      );
    }
    return this.props.children;
  }
}
