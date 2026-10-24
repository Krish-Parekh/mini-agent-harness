export type PreviewKind = "image" | "audio" | "video" | "pdf";

const BY_EXT: Record<string, PreviewKind> = {
  png: "image",
  jpg: "image",
  jpeg: "image",
  gif: "image",
  webp: "image",
  svg: "image",
  avif: "image",
  ico: "image",
  bmp: "image",
  mp3: "audio",
  wav: "audio",
  ogg: "audio",
  m4a: "audio",
  flac: "audio",
  aac: "audio",
  mp4: "video",
  webm: "video",
  mov: "video",
  pdf: "pdf",
};

export function previewKindForPath(path: string): PreviewKind | undefined {
  const name = path.slice(path.lastIndexOf("/") + 1);
  const dot = name.lastIndexOf(".");
  return dot > 0 ? BY_EXT[name.slice(dot + 1).toLowerCase()] : undefined;
}
