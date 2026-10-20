import { cva, type VariantProps } from "class-variance-authority";
import type { ButtonHTMLAttributes } from "react";

import { cn } from "@/lib/utils";

const filledShadow = "shadow-[inset_0_1px_0_rgba(255,255,255,0.14)]";

export const pillVariants = cva(
  "inline-flex items-center justify-center font-medium select-none transition-[transform,background-color,opacity] duration-150 ease-out active:scale-[0.96] disabled:pointer-events-none disabled:opacity-50",
  {
    variants: {
      variant: {
        primary: `bg-ink text-canvas hover:opacity-90 ${filledShadow}`,
        secondary: "bg-surface text-ink shadow-btn hover:bg-inset aria-expanded:bg-hover",
        ghost: "bg-hover-2 text-ink hover:bg-line-strong",
        brand: `bg-brand text-white hover:bg-brand-ink ${filledShadow}`,
        success: `bg-green text-white hover:brightness-95 ${filledShadow}`,
        danger: `bg-red text-white hover:brightness-95 ${filledShadow}`,
        quiet: "text-ink hover:bg-hover",
      },
      size: {
        xs: "h-7 gap-1 rounded-full px-2.5 text-[12px] font-normal leading-none",
        sm: "h-[27px] gap-1.5 rounded-full px-3 text-[13px] leading-none",
        md: "gap-2 rounded-full px-4 py-[9px] text-sm leading-none",
      },
    },
    defaultVariants: { variant: "secondary", size: "md" },
  },
);

export function Pill({
  variant,
  size,
  className,
  type = "button",
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & VariantProps<typeof pillVariants>) {
  return (
    <button
      type={type}
      className={cn(pillVariants({ variant, size }), className)}
      {...props}
    />
  );
}
