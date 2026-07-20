/**
 * Stable boundary for a future PowerPoint renderer implementation.
 * @typedef {{ outputPath: string, warnings: string[] }} RenderResult
 */
export class PresentationRenderer {
  /** @returns {Promise<RenderResult>} */
  async render(_deckSpec) {
    throw new Error("No PowerPoint renderer adapter has been selected yet.");
  }
}
