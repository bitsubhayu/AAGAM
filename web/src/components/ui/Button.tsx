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
      "inline-flex items-center justify-center font-medium rounded-full transition-all duration-150 focus:outline-none focus:ring-2 focus:ring-accent/40 disabled:opacity-50 disabled:cursor-not-allowed select-none";

    const sizeStyles = {
      sm: "text-xs px-3 py-1.5 gap-1.5",
      md: "text-xs px-4 py-2 gap-2",
      lg: "text-sm px-5 py-2.5 gap-2.5",
    };

    const variantStyles = {
      primary:
        "bg-accent hover:bg-[#D45730] text-white shadow-pill active:scale-[0.98]",
      secondary:
        "bg-[#F0EDE7] hover:bg-white text-text-primary border border-[rgba(26,23,18,0.10)] shadow-sm",
      outline:
        "border border-[rgba(26,23,18,0.15)] bg-transparent hover:bg-[#F0EDE7] text-text-primary",
      ghost:
        "bg-transparent hover:bg-[#F0EDE7] text-text-secondary hover:text-text-primary",
      destructive:
        "bg-hazard-alert hover:bg-[#D45730] text-white shadow-pill",
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
