import type { AttachmentRef } from "@/lib/api";
import { supabase } from "@/lib/supabase";

export const MAX_ATTACHMENTS = 10;
const MAX_FILE_BYTES = 25 * 1024 * 1024;
const MAX_IMAGE_BYTES = 5 * 1024 * 1024;
const MAX_IMAGE_EDGE = 2000;
const IMAGE_TYPES = ["image/png", "image/jpeg", "image/webp", "image/gif"];
const KEPT_IMAGE_TYPES = ["image/jpeg", "image/webp"];
const BUCKET = "attachments";

export type DraftAttachment = {
  id: string;
  name: string;
  source: File | AttachmentRef;
  kind: "image" | "file";
  previewUrl?: string;
};

export async function prepareAttachment(file: File): Promise<DraftAttachment> {
  if (file.size === 0) throw new Error(`${file.name} is empty.`);
  if (file.size > MAX_FILE_BYTES) throw new Error(`${file.name} is larger than 25 MB.`);
  const image = IMAGE_TYPES.includes(file.type) ? await reencodeImage(file) : null;
  if (!image) return { id: crypto.randomUUID(), name: file.name, source: file, kind: "file" };
  if (image.size > MAX_IMAGE_BYTES) throw new Error(`${file.name} is larger than 5 MB.`);
  return {
    id: crypto.randomUUID(),
    name: file.name,
    source: image,
    kind: "image",
    previewUrl: URL.createObjectURL(image),
  };
}

async function reencodeImage(file: File): Promise<File | null> {
  let bitmap: ImageBitmap;
  try {
    bitmap = await createImageBitmap(file);
  } catch {
    return null;
  }
  const scale = Math.min(1, MAX_IMAGE_EDGE / Math.max(bitmap.width, bitmap.height));
  const canvas = new OffscreenCanvas(
    Math.max(1, Math.round(bitmap.width * scale)),
    Math.max(1, Math.round(bitmap.height * scale)),
  );
  canvas.getContext("2d")?.drawImage(bitmap, 0, 0, canvas.width, canvas.height);
  bitmap.close();
  const type = KEPT_IMAGE_TYPES.includes(file.type) ? file.type : "image/png";
  const blob = await canvas.convertToBlob({ type, quality: 0.9 });
  return new File([blob], file.name, { type: blob.type });
}

export async function uploadAttachments(drafts: DraftAttachment[]): Promise<AttachmentRef[]> {
  if (drafts.length === 0) return [];
  const { data } = await supabase.auth.getSession();
  const userId = data.session?.user.id;
  if (!userId) throw new Error("Sign in to attach files.");
  return Promise.all(
    drafts.map(async ({ source, kind }) => {
      if (!(source instanceof File)) return source;
      const path = `${userId}/${crypto.randomUUID()}`;
      const mime = source.type || "application/octet-stream";
      const { error } = await supabase.storage
        .from(BUCKET)
        .upload(path, source, { contentType: mime });
      if (error) throw new Error(`Could not upload ${source.name}: ${error.message}`);
      return { path, name: source.name, mime, size: source.size, kind };
    }),
  );
}

export async function signedAttachmentUrl(attachment: AttachmentRef): Promise<string> {
  const { data, error } = await supabase.storage
    .from(BUCKET)
    .createSignedUrl(
      attachment.path,
      3600,
      attachment.kind === "file" ? { download: attachment.name } : undefined,
    );
  if (error) throw error;
  return data.signedUrl;
}
