import React from "react";

export const Skeleton: React.FC<React.HTMLAttributes<HTMLDivElement>> = ({
  className = "",
  ...props
}) => {
  return (
    <div
      className={`animate-pulse bg-[#F0EDE7] rounded ${className}`}
      {...props}
    />
  );
};
