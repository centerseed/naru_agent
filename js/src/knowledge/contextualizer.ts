/**
 * Contextual Retrieval: enrich chunks with situational context at ingest time.
 *
 * Anthropic research shows this reduces retrieval failure by 49-67%.
 * Cost: runs once at ingestion; zero overhead at query time.
 */

import { generateText, type LanguageModel } from "ai";

export interface ChunkContextualizerConfig {
  model: LanguageModel;
}

const PROMPT_TEMPLATE = `<document>
{document}
</document>

以下是要定位的 chunk：
<chunk>
{chunk}
</chunk>

請用一到三句話說明這個 chunk 在整份文件中的位置和背景脈絡，\
目的是改善向量搜索的準確度。只輸出這段說明，不要其他內容。`;

export class ChunkContextualizer {
  private readonly model: LanguageModel;

  constructor(config: ChunkContextualizerConfig) {
    this.model = config.model;
  }

  async contextualize(chunk: string, fullDocument: string): Promise<string> {
    const prompt = PROMPT_TEMPLATE
      .replace("{document}", fullDocument.replaceAll("{chunk}", "\\{chunk\\}"))
      .replace("{chunk}", chunk);

    const { text } = await generateText({
      model: this.model,
      messages: [{ role: "user", content: prompt }],
    });

    return `${text.trim()}\n${chunk}`;
  }

  async contextualizeMany(
    chunks: string[],
    fullDocument: string,
    concurrency = 5,
  ): Promise<string[]> {
    const results: string[] = new Array(chunks.length);
    let nextIndex = 0;

    const worker = async () => {
      while (nextIndex < chunks.length) {
        const i = nextIndex++;
        results[i] = await this.contextualize(chunks[i], fullDocument);
      }
    };

    await Promise.all(
      Array.from(
        { length: Math.min(concurrency, chunks.length) },
        () => worker(),
      ),
    );
    return results;
  }
}
