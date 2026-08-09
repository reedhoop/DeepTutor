import test from "node:test";
import assert from "node:assert/strict";
import { cleanTranscript } from "../hooks/useVoiceRecorder";

// ---------------------------------------------------------------------------
// cleanTranscript — defensive SenseVoice-style control-tag stripping. ASR models
// prefix transcripts with `<|zh|>`, `<|en|>`, `<|NEUTRAL|>`, `<|Happy|>`,
// `<|Basketball|>`…; those are model markers, not spoken content.
// ---------------------------------------------------------------------------

test("cleanTranscript strips leading language tag", () => {
  assert.equal(cleanTranscript("<|zh|>你好世界"), "你好世界");
});

test("cleanTranscript strips emotion/event tags anywhere in the string", () => {
  assert.equal(
    cleanTranscript("<|en|><|Happy|>Hello there <|Basketball|>"),
    "Hello there",
  );
});

test("cleanTranscript leaves the remaining text intact", () => {
  assert.equal(cleanTranscript("<|zh|>勾股定理的证明"), "勾股定理的证明");
});

test("cleanTranscript collapses internal whitespace runs", () => {
  assert.equal(cleanTranscript("  多个    空格 "), "多个 空格");
});

test("cleanTranscript is a no-op on plain text", () => {
  assert.equal(cleanTranscript("今天讲一次函数"), "今天讲一次函数");
});
