import { describe, expect, it } from "vitest";
import * as box from "../src/main/crypto";

// produced by the server's Python (`cryptography`): the two must agree byte for byte
const b = (s: string) => Buffer.from(s, "base64");
const V = {
  clientSk: b("AQIDBAUGBwgJCgsMDQ4PEBESExQVFhcYGRobHB0eHyA="),
  serverSk: b("ZWZnaGlqa2xtbm9wcXJzdHV2d3h5ent8fX5/gIGCg4Q="),
  clientPk: b("B6N8vBQgk8i3VdwbEOhstCY3StFqqFPtC9/AsrhtHHw="),
  serverPk: b("VxR2nRFr92Q2rnS8eT0sMK0ZA8WaxSc4BcfiaYtBDDY="),
  key: b("kw878q5tUXKJ7G9zxHemHSiN0IYUkrbS2JRfz645FMA="),
  nonce: b("AAECAwQFBgcICQoL"),
  sealed: b("nXWYcoCnu0lQZYGFxDaVEJ9TQh3b50fsfh4GJV2fYKOC"),
  secret: b("yMnKy8zNzs/Q0Q=="),
  codeId: "b2bcf0224b84879d08b9c24bc0da547572e936a09e7c9bd0debbca24da704f8e",
  pairKey: b("jzVXSmhT/tM4vZiUgV5E9ddU98ZDO2a34whwsbIzv5A="),
  mac: b("rWDeEvhZcENAquiPKDXUscUzC2Zz2VQJy793xrGIc/Q="),
};

describe("the relay's box", () => {
  it("derives the same public keys as the server", () => {
    expect(box.publicFromSecret(V.clientSk).equals(V.clientPk)).toBe(true);
    expect(box.publicFromSecret(V.serverSk).equals(V.serverPk)).toBe(true);
  });

  it("arrives at the same key from either side", () => {
    expect(box.boxKey(V.clientSk, V.serverPk, V.clientPk, V.serverPk).equals(V.key)).toBe(true);
    expect(box.boxKey(V.serverSk, V.clientPk, V.clientPk, V.serverPk).equals(V.key)).toBe(true);
  });

  it("seals exactly as Python's ChaCha20Poly1305 does, and opens what it sealed", () => {
    const sealed = box.seal(V.key, V.nonce, Buffer.from('{"hello":"world"}'), "c2s");
    expect(sealed.toString("base64")).toBe(V.sealed.toString("base64"));
    expect(box.open(V.key, V.nonce, V.sealed, "c2s").toString()).toBe('{"hello":"world"}');
  });

  it("refuses a box turned around or tampered with", () => {
    expect(() => box.open(V.key, V.nonce, V.sealed, "s2c")).toThrow();
    const bent = Buffer.from(V.sealed);
    bent[0] = bent[0]! ^ 1;
    expect(() => box.open(V.key, V.nonce, bent, "c2s")).toThrow();
  });

  it("sends the secret's hash, never the secret, and checks the welcome's MAC", () => {
    expect(box.codeId(V.secret)).toBe(V.codeId);
    expect(box.pairKey(V.secret).equals(V.pairKey)).toBe(true);
    expect(box.welcomeMac(V.secret, V.serverPk, V.clientPk).equals(V.mac)).toBe(true);
    expect(box.checkWelcome(V.secret, V.serverPk, V.clientPk, V.mac)).toBe(true);
    // a relay that swaps in a key of its own cannot make the MAC fit it
    expect(box.checkWelcome(V.secret, box.newKeyPair().public, V.clientPk, V.mac)).toBe(false);
  });
});
