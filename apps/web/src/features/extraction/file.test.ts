import { describe, expect, it, vi } from "vitest";
import {
  fileRequest,
  MAX_PDF_FILE_BYTES,
  validatePdfFile,
} from "./file";

function pdfFile(parts: BlobPart[], name = "report.pdf", type = "application/pdf"): File {
  return new File(parts, name, { type });
}

describe("PDF upload validation", () => {
  it("accepts a non-empty PDF signature and builds the request", async () => {
    const file = pdfFile(["%PDF-1.7\nvalid test fixture"]);

    await expect(validatePdfFile(file)).resolves.toBeUndefined();
    await expect(fileRequest(file, "management-review", 8, "request-1"))
      .resolves.toMatchObject({
        input_mode: "file",
        file_name: "report.pdf",
        declared_media_type: "application/pdf",
      });
  });

  it("rejects oversized files before reading or encoding them", async () => {
    const oversized = {
      name: "large.pdf",
      type: "application/pdf",
      size: MAX_PDF_FILE_BYTES + 1,
      slice: vi.fn(),
      arrayBuffer: vi.fn(),
    } as unknown as File;

    await expect(fileRequest(oversized, "board-update", 10, "request-2"))
      .rejects.toThrow("25 MiB");
    expect(oversized.slice).not.toHaveBeenCalled();
    expect(oversized.arrayBuffer).not.toHaveBeenCalled();
  });

  it("rejects renamed non-PDF content before base64 encoding", async () => {
    const file = pdfFile(["This is plain text."], "renamed.pdf", "application/pdf");
    const fullRead = vi.spyOn(file, "arrayBuffer");

    await expect(fileRequest(file, "investor-summary", 6, "request-3"))
      .rejects.toThrow("not a valid PDF");
    expect(fullRead).not.toHaveBeenCalled();
  });

  it("rejects empty files before reading or encoding them", async () => {
    const file = pdfFile([]);
    const fullRead = vi.spyOn(file, "arrayBuffer");

    await expect(fileRequest(file, "management-review", 8, "request-4"))
      .rejects.toThrow("empty");
    expect(fullRead).not.toHaveBeenCalled();
  });
});
