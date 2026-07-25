import type { CreateJobRequest, DeckPurpose } from "./types";

function bytesToBase64(bytes: Uint8Array): string {
  const chunkSize = 0x8000;
  let binary = "";
  for (let offset = 0; offset < bytes.length; offset += chunkSize) {
    binary += String.fromCharCode(...bytes.subarray(offset, offset + chunkSize));
  }
  return btoa(binary);
}

export async function fileRequest(
  file: File,
  deckPurpose: DeckPurpose,
  slideCount: number,
  requestKey: string,
): Promise<CreateJobRequest> {
  return {
    input_mode: "file",
    file_name: file.name,
    file_content_base64: bytesToBase64(new Uint8Array(await file.arrayBuffer())),
    declared_media_type: file.type || "application/octet-stream",
    deck_purpose: deckPurpose,
    slide_count: slideCount,
    request_key: requestKey,
  };
}
