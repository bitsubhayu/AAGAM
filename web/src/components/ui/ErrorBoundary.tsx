import { Component, type ErrorInfo, type ReactNode } from "react";
import { AlertCircle, RotateCcw } from "lucide-react";
import { Button } from "./Button";

interface ErrorBoundaryProps {
  children: ReactNode;
  fallbackTitle?: string;
  fallbackMessage?: string;
}

interface ErrorBoundaryState {
  hasError: boolean;
  error?: Error;
}

export class ErrorBoundary extends Component<ErrorBoundaryProps, ErrorBoundaryState> {
  public state: ErrorBoundaryState = {
    hasError: false,
  };

  public static getDerivedStateFromError(error: Error): ErrorBoundaryState {
    return { hasError: true, error };
  }

  public componentDidCatch(error: Error, errorInfo: ErrorInfo) {
    console.error("ErrorBoundary caught an error:", error, errorInfo);
  }

  public render() {
    if (this.state.hasError) {
      return (
        <div className="p-6 bg-surface border border-hazard-alert/30 rounded-lg text-center space-y-3 font-sans">
          <div className="flex items-center justify-center gap-2 text-hazard-alert font-bold text-sm">
            <AlertCircle className="w-5 h-5 shrink-0" />
            <span>{this.props.fallbackTitle || "Something went wrong rendering this view."}</span>
          </div>
          <p className="text-xs text-text-secondary max-w-md mx-auto">
            {this.props.fallbackMessage || this.state.error?.message || "An unexpected rendering error occurred."}
          </p>
          <div className="pt-2">
            <Button
              variant="outline"
              size="sm"
              onClick={() => this.setState({ hasError: false, error: undefined })}
            >
              <RotateCcw className="w-3.5 h-3.5 mr-1" />
              <span>Retry Component</span>
            </Button>
          </div>
        </div>
      );
    }

    return this.props.children;
  }
}
