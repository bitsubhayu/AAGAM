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
    "inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[11px] font-semibold select-none";

  const variantStyles: Record<BadgeVariant, string> = {
    advisory:
      "bg-[#FDF3DC] text-[#7A5C00] border border-[#D9A441]/30",
    watch:
      "bg-[#FEE9D6] text-[#7A3300] border border-[#E07B2E]/30",
    alert:
      "bg-accent-soft text-accent border border-accent/30 font-bold",
    normal:
      "bg-[#E4F5EE] text-[#1A6645] border border-[#3D9970]/30",
    neutral:
      "bg-[#F0EDE7] text-text-secondary border border-[rgba(26,23,18,0.10)]",
    outline:
      "bg-transparent text-text-muted border border-[rgba(26,23,18,0.15)]",
    gfs:
      "bg-[#EBF2FD] text-[#2B55A8] border border-[#4C7BD9]/30 font-mono",
    ifs:
      "bg-[#F0EBFD] text-[#4B30A8] border border-[#8B6FD9]/30 font-mono",
    icon:
      "bg-[#E8F5EF] text-[#1E6647] border border-[#4FA37A]/30 font-mono",
    aifs:
      "bg-[#FDF3DC] text-[#6B4B00] border border-[#C98A1E]/30 font-mono",
    blend:
      "bg-[#EBF2FD] text-[#2B55A8] border border-[#4C7BD9]/40 font-mono font-semibold",
  };

  const renderIcon = () => {
    if (!showIcon) return null;
    switch (variant) {
      case "alert":
        return <AlertCircle className="w-3 h-3 text-accent shrink-0" />;
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
