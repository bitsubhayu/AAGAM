import React from "react";
import { AlertCircle, AlertTriangle, Info, CheckCircle2 } from "lucide-react";

export type BadgeVariant =
  | "advisory"
  | "watch"
  | "alert"
  | "normal"
  | "neutral"
  | "gfs"
  | "ifs"
  | "icon"
  | "aifs"
  | "blend"
  | "outline";

interface BadgeProps extends React.HTMLAttributes<HTMLSpanElement> {
  variant?: BadgeVariant;
  showIcon?: boolean;
}

export const Badge: React.FC<BadgeProps> = ({
  variant = "neutral",
  showIcon = false,
  className = "",
  children,
  ...props
}) => {
  const baseStyles =
    "inline-flex items-center gap-1 px-2 py-0.5 rounded text-[11px] font-medium select-none border";

  const variantStyles: Record<BadgeVariant, string> = {
    advisory:
      "bg-amber-950/40 text-hazard-advisory border-amber-800/60",
    watch:
      "bg-orange-950/40 text-hazard-watch border-orange-800/60",
    alert:
      "bg-red-950/40 text-hazard-alert border-red-800/60 font-semibold",
    normal:
      "bg-emerald-950/40 text-hazard-normal border-emerald-800/60",
    neutral:
      "bg-[#21262d] text-text-secondary border-border",
    outline:
      "bg-transparent text-text-muted border-border",
    gfs:
      "bg-blue-950/40 text-model-gfs border-blue-800/60 font-mono",
    ifs:
      "bg-emerald-950/40 text-model-ifs border-emerald-800/60 font-mono",
    icon:
      "bg-amber-950/40 text-model-icon border-amber-800/60 font-mono",
    aifs:
      "bg-purple-950/40 text-model-aifs border-purple-800/60 font-mono",
    blend:
      "bg-blue-900/40 text-blue-300 border-blue-600/70 font-mono font-semibold",
  };

  const renderIcon = () => {
    if (!showIcon) return null;
    switch (variant) {
      case "alert":
        return <AlertCircle className="w-3 h-3 text-hazard-alert shrink-0" />;
      case "watch":
        return <AlertTriangle className="w-3 h-3 text-hazard-watch shrink-0" />;
      case "advisory":
        return <Info className="w-3 h-3 text-hazard-advisory shrink-0" />;
      case "normal":
        return <CheckCircle2 className="w-3 h-3 text-hazard-normal shrink-0" />;
      default:
        return null;
    }
  };

  return (
    <span className={`${baseStyles} ${variantStyles[variant]} ${className}`} {...props}>
      {renderIcon()}
      {children}
    </span>
  );
};
