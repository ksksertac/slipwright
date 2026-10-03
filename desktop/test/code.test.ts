import { describe, expect, it } from "vitest";
import { CodeError, pack, unpack } from "../src/main/code";

const SECRET = Buffer.from([0, 1, 2, 3, 4, 5, 6, 7, 8, 9]);

// made by the server's own `slipwright.workers.pack(address, bytes(range(10)))`
const FROM_PYTHON: [string, string, boolean][] = [
  ["SW-G3G5-804A-1YG0-0041-0610-50R3-GG29-B", "http://192.168.1.20:8000", false],
  ["SW-G5JR-0E42-J1YR-0041-0610-50R3-GG28-R", "https://203.0.113.5:8443", false],
  ["SW-G6T3-MEHR-76EH-F5XS-PRTB-G5SJ-QGRB-DE1P-6ABK-3DXP-JYY0-0041-0610-50R3-GG2C-6", "https://slip.example.com/x", false],
  ["SW-421Y-G000-4106-1050-R3GG-2BN", "http://localhost:8000", true],
];

describe("a connection code", () => {
  it.each(FROM_PYTHON)("made by the server is read the same here: %s", (code, url, nearby) => {
    const got = unpack(code);
    expect(got.address).toEqual({ kind: "url", url, nearby });
    expect(got.secret.equals(SECRET)).toBe(true);
  });

  it("forgives lower case, spaces, and O / I / L typed for 0 / 1", () => {
    const sloppy = " sw-g3g5 8O4a-1yg0-OO41-O61O-5Or3-gg29-b ";
    expect(unpack(sloppy).address).toEqual({ kind: "url", url: "http://192.168.1.20:8000", nearby: false });
  });

  it("with a character wrong or missing does not add up, before the network is touched", () => {
    expect(() => unpack("SW-G3G5-804A-1YG0-0041-0610-50R3-GG29-C")).toThrow(CodeError);
    expect(() => unpack("SW-G3G5-804A-1YG0-0041-0610-50R3-GG29")).toThrow(CodeError);
  });

  it("from something else says so", () => {
    expect(() => unpack("XX-1234")).toThrow(/start with SW-/);
    expect(() => unpack("SW-12U4")).toThrow(/no 'U'/);
  });

  it("can carry the relay and its room (kind 5)", () => {
    const room = "00112233445566778899aabbccddeeff";
    const code = pack({ kind: "relay", host: "relay.slipwright.app", room }, SECRET);
    expect(code.startsWith("SW-")).toBe(true);
    expect(unpack(code)).toEqual({ address: { kind: "relay", host: "relay.slipwright.app", room }, secret: SECRET });
  });

  it("packed here is the very code Python packs", () => {
    expect(pack({ kind: "url", url: "https://slip.example.com/x", nearby: false }, SECRET)).toBe(FROM_PYTHON[2]![0]);
    expect(pack({ kind: "url", url: "http://localhost:8000", nearby: true }, SECRET)).toBe(FROM_PYTHON[3]![0]);
  });
});
