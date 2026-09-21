import React from "react";

export interface CardProps extends React.HTMLAttributes<HTMLDivElement> {
  compact?: boolean;
}

export const Card: React.FC<CardProps> = ({
  className = "",
  compact = false,
  children,
  ...props
}) => {
  return (
    <div
      className={`bg-surface border border-border rounded-lg shadow-sm ${
        compact ? "p-3" : "p-4"
      } ${className}`}
      {...props}
    >
      {children}
    </div>
  );
};

export const CardHeader: React.FC<React.HTMLAttributes<HTMLDivElement>> = ({
  className = "",
  children,
  ...props
}) => {
  return (
    <div
      className={`flex items-center justify-between pb-3 mb-3 border-b border-border/60 ${className}`}
      {...props}
    >
      {children}
    </div>
  );
};

export const CardTitle: React.FC<React.HTMLAttributes<HTMLHeadingElement>> = ({
  className = "",
  children,
  ...props
}) => {
  return (
    <h3
      className={`text-sm font-semibold text-text-primary flex items-center gap-2 ${className}`}
      {...props}
    >
      {children}
    </h3>
  );
};

export const CardDescription: React.FC<React.HTMLAttributes<HTMLParagraphElement>> = ({
  className = "",
  children,
  ...props
}) => {
  return (
    <p className={`text-xs text-text-muted mt-0.5 ${className}`} {...props}>
      {children}
    </p>
  );
};
