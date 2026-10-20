import { cn } from "@/lib/utils";

type Tone = "neutral" | "green" | "orange" | "red" | "brand";

const TONES: Record<Tone, { cls: string; ring: string }> = {
  neutral: { cls: "bg-field text-ink-2", ring: "var(--shadow-hairline)" },
  green: {
    cls: "bg-green-tint text-green",
    ring: "0 0 0 1px color-mix(in oklch, var(--green) 28%, transparent)",
  },
  orange: {
    cls: "bg-orange-tint text-orange",
    ring: "0 0 0 1px color-mix(in oklch, var(--orange) 28%, transparent)",
  },
  red: {
    cls: "bg-red-tint text-red",
    ring: "0 0 0 1px color-mix(in oklch, var(--red) 28%, transparent)",
  },
  brand: {
    cls: "bg-brand-tint text-brand-ink",
    ring: "0 0 0 1px color-mix(in oklch, var(--brand) 28%, transparent)",
  },
};

export function ValuePill({
  children,
  tone = "neutral",
  className,
}: {
  children: React.ReactNode;
  tone?: Tone;
  className?: string;
}) {
  const t = TONES[tone];
  return (
    <span
      className={cn(
        "inline-flex items-center rounded-full px-1.5 align-middle text-[12px] font-medium tabular-nums",
        t.cls,
        className,
      )}
      style={{ boxShadow: t.ring }}
    >
      {children}
    </span>
  );
}
