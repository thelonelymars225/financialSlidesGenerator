import type { CreateJobRequest, DeckPurpose } from "./types";

export const MAX_PDF_FILE_BYTES = 25 * 1024 * 1024;
const PDF_SIGNATURE = new Uint8Array([0x25, 0x50, 0x44, 0x46, 0x2d]);

export class PdfValidationError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "PdfValidationError";
  }
}

export async function validatePdfFile(file: File): Promise<void> {
  if (file.size === 0) {
    throw new PdfValidationError("The selected PDF is empty. Choose a file with content.");
  }
  if (file.size > MAX_PDF_FILE_BYTES) {
    throw new PdfValidationError("The selected PDF exceeds the 25 MiB upload limit.");
  }

  const hasPdfName = file.name.toLowerCase().endsWith(".pdf");
  const hasPdfMediaType = file.type.toLowerCase() === "application/pdf";
  if (!hasPdfName && !hasPdfMediaType) {
    throw new PdfValidationError("Choose a PDF file with a .pdf name or PDF media type.");
  }

  const header = new Uint8Array(await file.slice(0, PDF_SIGNATURE.length).arrayBuffer());
  if (
    header.length < PDF_SIGNATURE.length
    || PDF_SIGNATURE.some((byte, index) => header[index] !== byte)
  ) {
    throw new PdfValidationError("The selected file is not a valid PDF.");
  }
}

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
  await validatePdfFile(file);
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
