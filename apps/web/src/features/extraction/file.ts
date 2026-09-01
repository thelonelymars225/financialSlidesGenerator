import type { CreateFileJobRequest, DeckPurpose } from "./types";

export async function fileRequest(
  file: File,
  deckPurpose: DeckPurpose,
  slideCount: number,
  requestKey: string,
): Promise<CreateFileJobRequest> {
  return {
    input_mode: "file",
    file,
    deck_purpose: deckPurpose,
    slide_count: slideCount,
    request_key: requestKey,
  };
}
