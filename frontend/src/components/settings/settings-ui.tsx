import { cn } from "@/lib/utils";

export function SettingsPage({
  title,
  children,
}: {
  title: string;
  children: React.ReactNode;
}) {
  return (
    <div className="mx-auto flex w-full max-w-3xl flex-col gap-8 px-6 pt-10 pb-16">
      <h1 className="text-xl font-medium tracking-tight">{title}</h1>
      {children}
    </div>
  );
}

export function SettingsGroup({
  title,
  description,
  children,
}: {
  title?: string;
  description?: string;
  children: React.ReactNode;
}) {
  return (
    <section className="flex flex-col gap-2.5">
      {title && (
        <div className="flex flex-col gap-0.5 px-1">
          <h2 className="text-sm text-muted-foreground">{title}</h2>
          {description && (
            <p className="text-xs text-muted-foreground/80">{description}</p>
          )}
        </div>
      )}
      <div className="flex flex-col rounded-xl bg-card px-4">{children}</div>
    </section>
  );
}

export function SettingsRow({
  title,
  description,
  children,
  className,
}: {
  title: React.ReactNode;
  description?: React.ReactNode;
  children?: React.ReactNode;
  className?: string;
}) {
  return (
    <div
      className={cn(
        "flex flex-col gap-3 border-b border-border py-4 last:border-b-0 sm:flex-row sm:items-center sm:justify-between sm:gap-6",
        className,
      )}
    >
      <div className="flex min-w-0 flex-col gap-0.5">
        <div className="text-sm text-foreground">{title}</div>
        {description && (
          <div className="text-sm break-words text-muted-foreground">
            {description}
          </div>
        )}
      </div>
      {children && (
        <div className="flex shrink-0 items-center gap-2">{children}</div>
      )}
    </div>
  );
}

export function SettingsEmpty({ children }: { children: React.ReactNode }) {
  return (
    <p className="py-4 text-sm text-muted-foreground">{children}</p>
  );
}
