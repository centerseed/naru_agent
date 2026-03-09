"use strict";
/**
 * Contextual Retrieval: enrich chunks with situational context at ingest time.
 *
 * Anthropic research shows this reduces retrieval failure by 49-67%.
 * Cost: runs once at ingestion; zero overhead at query time.
 */
Object.defineProperty(exports, "__esModule", { value: true });
exports.ChunkContextualizer = void 0;
const ai_1 = require("ai");
const PROMPT_TEMPLATE = `<document>
{document}
</document>

以下是要定位的 chunk：
<chunk>
{chunk}
</chunk>

請用一到三句話說明這個 chunk 在整份文件中的位置和背景脈絡，\
目的是改善向量搜索的準確度。只輸出這段說明，不要其他內容。`;
class ChunkContextualizer {
    model;
    constructor(config) {
        this.model = config.model;
    }
    async contextualize(chunk, fullDocument) {
        const prompt = PROMPT_TEMPLATE
            .replace("{document}", fullDocument.replaceAll("{chunk}", "\\{chunk\\}"))
            .replace("{chunk}", chunk);
        const { text } = await (0, ai_1.generateText)({
            model: this.model,
            messages: [{ role: "user", content: prompt }],
        });
        return `${text.trim()}\n${chunk}`;
    }
    async contextualizeMany(chunks, fullDocument, concurrency = 5) {
        const results = new Array(chunks.length);
        let nextIndex = 0;
        const worker = async () => {
            while (nextIndex < chunks.length) {
                const i = nextIndex++;
                results[i] = await this.contextualize(chunks[i], fullDocument);
            }
        };
        await Promise.all(Array.from({ length: Math.min(concurrency, chunks.length) }, () => worker()));
        return results;
    }
}
exports.ChunkContextualizer = ChunkContextualizer;
