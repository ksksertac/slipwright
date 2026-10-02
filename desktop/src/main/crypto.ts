// The relay's box (docs/machines-protocol.md §3), in Node's own `crypto` so the app needs
// no native module for it -- the server does the same in Python's `cryptography`, and the
// tests hold both to the same vectors.
//
// Node takes X25519 keys as KeyObjects, not raw bytes, so raw keys are wrapped in the
// fixed DER prefixes for PKCS#8 / SPKI. That is what JWK import would do underneath, with
// one fewer encoding (base64url) to get wrong.

import {
  createCipheriv,
  createDecipheriv,
  createHash,
  createHmac,
  createPrivateKey,
  createPublicKey,
  diffieHellman,
  generateKeyPairSync,
  hkdfSync,
  randomBytes,
  timingSafeEqual,
  type KeyObject,
} from "node:crypto";

const PKCS8_X25519 = Buffer.from("302e020100300506032b656e04220420", "hex");
const SPKI_X25519 = Buffer.from("302a300506032b656e032100", "hex");
const INFO = Buffer.from("slipwright-relay-v1");
const PAIR_INFO = Buffer.from("slipwright-relay-pair");

export type Direction = "c2s" | "s2c";

export interface KeyPair {
  secret: Buffer;
  public: Buffer;
}

export function privateKey(raw: Uint8Array): KeyObject {
  return createPrivateKey({ key: Buffer.concat([PKCS8_X25519, raw]), format: "der", type: "pkcs8" });
}

export function publicKey(raw: Uint8Array): KeyObject {
  return createPublicKey({ key: Buffer.concat([SPKI_X25519, raw]), format: "der", type: "spki" });
}

export function publicFromSecret(secret: Uint8Array): Buffer {
  const der = createPublicKey(privateKey(secret)).export({ format: "der", type: "spki" });
  return Buffer.from(der.subarray(der.length - 32));
}

export function newKeyPair(): KeyPair {
  const { privateKey: sk } = generateKeyPairSync("x25519");
  const der = sk.export({ format: "der", type: "pkcs8" });
  const secret = Buffer.from(der.subarray(der.length - 32));
  return { secret, public: publicFromSecret(secret) };
}

/** The shared key of one guest and one host. The salt is always client ‖ server, whichever
 *  side computes it, so both arrive at the same key. */
export function boxKey(mySecret: Uint8Array, theirPublic: Uint8Array, clientPk: Uint8Array, serverPk: Uint8Array): Buffer {
  const shared = diffieHellman({ privateKey: privateKey(mySecret), publicKey: publicKey(theirPublic) });
  return Buffer.from(hkdfSync("sha256", shared, Buffer.concat([clientPk, serverPk]), INFO, 32));
}

/** ChaCha20-Poly1305, laid out as Python's AEAD lays it out: ciphertext ‖ 16-byte tag. */
export function seal(key: Uint8Array, nonce: Uint8Array, plaintext: Uint8Array, dir: Direction): Buffer {
  const cipher = createCipheriv("chacha20-poly1305", key, nonce, { authTagLength: 16 });
  cipher.setAAD(Buffer.from(dir), { plaintextLength: plaintext.length });
  const body = Buffer.concat([cipher.update(plaintext), cipher.final()]);
  return Buffer.concat([body, cipher.getAuthTag()]);
}

/** Throws when the box was tampered with, sealed with another key, or for the other direction. */
export function open(key: Uint8Array, nonce: Uint8Array, sealed: Uint8Array, dir: Direction): Buffer {
  if (sealed.length < 16) throw new Error("a box too short to hold its tag");
  const decipher = createDecipheriv("chacha20-poly1305", key, nonce, { authTagLength: 16 });
  decipher.setAAD(Buffer.from(dir), { plaintextLength: sealed.length - 16 });
  decipher.setAuthTag(sealed.subarray(sealed.length - 16));
  return Buffer.concat([decipher.update(sealed.subarray(0, sealed.length - 16)), decipher.final()]);
}

export function nonce(): Buffer {
  return randomBytes(12);
}

/** What the guest sends in `hello` instead of the secret: the server keeps this hash. */
export function codeId(secret: Uint8Array): string {
  return createHash("sha256").update(secret).digest("hex");
}

export function pairKey(secret: Uint8Array): Buffer {
  return createHmac("sha256", secret).update(PAIR_INFO).digest();
}

/** The host's proof that it holds the code's secret, binding both public keys: a relay
 *  that swapped in a key of its own could not produce it. */
export function welcomeMac(secret: Uint8Array, serverPk: Uint8Array, clientPk: Uint8Array): Buffer {
  return createHmac("sha256", pairKey(secret)).update(Buffer.concat([serverPk, clientPk])).digest();
}

export function checkWelcome(secret: Uint8Array, serverPk: Uint8Array, clientPk: Uint8Array, mac: Uint8Array): boolean {
  const want = welcomeMac(secret, serverPk, clientPk);
  return mac.length === want.length && timingSafeEqual(want, mac);
}
