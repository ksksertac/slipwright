import { randomBytes } from "node:crypto";
import { describe, expect, it } from "vitest";
import { Joiner, PART_BYTES, split } from "../src/main/parts";

describe("a message cut into parts", () => {
  it("fits one part when small", () => {
    const parts = split(Buffer.from("{}"), "aaaaaaaaaaaaaaaa");
    expect(parts).toEqual([{ mid: "aaaaaaaaaaaaaaaa", part: 0, parts: 1, data: Buffer.from("{}").toString("base64") }]);
    expect(new Joiner().add(parts[0]!)!.toString()).toBe("{}");
  });

  it("is cut at 512 KiB and joined whole, in whatever order the parts arrive", () => {
    const message = randomBytes(PART_BYTES * 2 + 1000);
    const parts = split(message);
    expect(parts).toHaveLength(3);
    expect(Buffer.from(parts[0]!.data, "base64")).toHaveLength(PART_BYTES);
    expect(parts[0]!.mid).toMatch(/^[0-9a-f]{16}$/);
    const joiner = new Joiner();
    expect(joiner.add(parts[2]!)).toBeNull();
    expect(joiner.add(parts[0]!)).toBeNull();
    expect(joiner.add(parts[1]!)!.equals(message)).toBe(true);
  });

  it("keeps two messages apart, and forgets one that never completes", () => {
    const a = split(randomBytes(PART_BYTES + 1));
    const b = split(randomBytes(PART_BYTES + 1));
    const joiner = new Joiner(1000);
    joiner.add(a[0]!, 0);
    joiner.add(b[0]!, 0);
    expect(joiner.add(b[1]!, 10)).not.toBeNull();
    expect(joiner.add(a[1]!, 5000)).toBeNull(); // a's first part was dropped as stale
  });

  it("refuses something that is not a part", () => {
    expect(() => new Joiner().add({ mid: "x", part: 3, parts: 2, data: "" })).toThrow();
  });
});
