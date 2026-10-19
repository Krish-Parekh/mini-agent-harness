import { HomeComposer } from "@/components/home-composer";
import { SidebarTrigger } from "@/components/ui/sidebar";

export default function Home() {
  return (
    <div className="flex min-h-full flex-col">
      <header className="flex h-14 shrink-0 items-center px-4">
        <SidebarTrigger />
      </header>
      <div className="flex flex-1 flex-col items-center justify-center gap-6 px-4 pb-24">
        <h1 className="text-2xl font-semibold tracking-tight">
          What should we build?
        </h1>
        <HomeComposer />
      </div>
    </div>
  );
}
