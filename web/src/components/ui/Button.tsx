import React from "react";
import { Loader2 } from "lucide-react";

export interface ButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: "primary" | "secondary" | "outline" | "ghost" | "destructive";
  size?: "sm" | "md" | "lg";
  isLoading?: boolean;
}

export const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(
  (
    {
      className = "",
      variant = "primary",
      size = "md",
      isLoading = false,
      disabled,
      children,
      ...props
    },
    ref
  ) => {
    const baseStyles =
      "inline-flex items-center justify-center font-medium rounded-md transition-colors focus:outline-none focus:ring-2 focus:ring-brand-blue/50 disabled:opacity-50 disabled:cursor-not-allowed select-none";

    const sizeStyles = {
      sm: "text-xs px-2.5 py-1.5 gap-1.5",
      md: "text-xs px-3.5 py-2 gap-2",
      lg: "text-sm px-4 py-2.5 gap-2.5",
    };

    const variantStyles = {
      primary:
        "bg-brand-blue hover:bg-blue-600 text-white shadow-sm active:bg-blue-700",
      secondary:
        "bg-[#21262d] hover:bg-[#30363d] text-text-primary border border-border",
      outline:
        "border border-border bg-transparent hover:bg-[#21262d] text-text-primary",
      ghost: "bg-transparent hover:bg-[#21262d] text-text-secondary hover:text-text-primary",
      destructive:
        "bg-hazard-alert hover:bg-red-600 text-white shadow-sm",
    };

    return (
      <button
        ref={ref}
        disabled={disabled || isLoading}
        className={`${baseStyles} ${sizeStyles[size]} ${variantStyles[variant]} ${className}`}
        {...props}
      >
        {isLoading && <Loader2 className="w-3.5 h-3.5 animate-spin" />}
        {children}
      </button>
    );
  }
);

Button.displayName = "Button";
