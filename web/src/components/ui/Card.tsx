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
      className={`bg-surface rounded-card shadow-card border border-[rgba(26,23,18,0.07)] transition-shadow duration-200 hover:shadow-card-hover ${
        compact ? "p-4" : "p-5"
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
      className={`flex items-center justify-between pb-3 mb-3 border-b border-[rgba(26,23,18,0.07)] ${className}`}
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
