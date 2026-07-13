import { describe, expect, it } from "bun:test";
import { ALLOWED_MODELS, isAllowedModel, listAllowedModels } from "../../src/codex/models";

describe("codex models", () => {
  describe("listAllowedModels", () => {
    it("retorna a lista no formato OpenAI { object: list, data: [...] }", () => {
      const result = listAllowedModels();

      expect(result.object).toBe("list");
      expect(Array.isArray(result.data)).toBe(true);
      expect(result.data.length).toBe(ALLOWED_MODELS.length);
    });

    it("cada item tem id, object=model, created e owned_by", () => {
      const result = listAllowedModels();

      for (const model of result.data) {
        expect(model.object).toBe("model");
        expect(typeof model.id).toBe("string");
        expect(typeof model.created).toBe("number");
        expect(model.owned_by).toBe("chatgpt-plan");
      }
    });

    it("inclui os modelos codex esperados", () => {
      const ids = listAllowedModels().data.map((m) => m.id);

      expect(ids).toContain("gpt-5.1-codex");
      expect(ids).toContain("gpt-5.1-codex-max");
      expect(ids).toContain("codex-mini-latest");
    });
  });

  describe("isAllowedModel", () => {
    it("retorna true para modelos da allowlist", () => {
      expect(isAllowedModel("gpt-5.1-codex")).toBe(true);
      expect(isAllowedModel("gpt-5.5")).toBe(true);
    });

    it("retorna false para modelos fora da allowlist", () => {
      expect(isAllowedModel("gpt-4o")).toBe(false);
      expect(isAllowedModel("")).toBe(false);
    });
  });
});
