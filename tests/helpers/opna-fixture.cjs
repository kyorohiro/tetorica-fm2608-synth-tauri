// SPDX-License-Identifier: BSD-3-Clause
// Authored register diagnostic. No game music or recorded observations.
const {gzipSync} = require('node:zlib');
function createOpnaFixture() {
  const writes = [], write = (port, register, value) => writes.push(0x56 + port, register, value);
  for (const offset of [0, 4, 8, 12]) {
    for (const [base, value] of [[0x30, 1], [0x40, 32], [0x50, 31], [0x60, 0], [0x70, 0], [0x80, 15], [0x90, 0]]) write(0, base + offset, value);
  }
  write(0, 0x29, 0x80); write(0, 0xb0, 7); write(0, 0xb4, 0xc0);
  write(0, 0xa4, 0x22); write(0, 0xa0, 0x22); write(0, 0x28, 0xf0);
  write(0, 0, 0); write(0, 1, 2); write(0, 7, 0x3e); write(0, 8, 10);
  write(0, 0x11, 48); write(0, 0x18, 0xd8); write(0, 0x10, 1);
  write(1, 1, 0xc2); write(1, 2, 8); write(1, 3, 0);
  write(1, 4, 9); write(1, 5, 0); write(1, 12, 255); write(1, 13, 255);
  write(1, 9, 0); write(1, 10, 0x60); write(1, 11, 120); write(1, 0, 0xb0);
  const sample = Buffer.from(Array.from({length:64}, (_, index) => index % 16 < 8 ? 0x11 : 0x99));
  const block = Buffer.alloc(15 + sample.length);
  block.set([0x67, 0x66, 0x81]); block.writeUInt32LE(8 + sample.length, 3);
  block.writeUInt32LE(0x200000, 7); block.writeUInt32LE(256, 11); sample.copy(block, 15);
  const commands = [...block, ...writes];
  for (let second = 0; second < 16; second++) commands.push(0x61, 0x44, 0xac);
  commands.push(0x66);
  const vgm = Buffer.alloc(256 + commands.length);
  vgm.set([0x56, 0x67, 0x6d, 0x20]); vgm.writeUInt32LE(vgm.length - 4, 4); vgm.writeUInt32LE(0x171, 8);
  vgm.writeUInt32LE(256 - 0x34, 0x34); vgm.writeUInt32LE(8000000, 0x48);
  vgm.writeUInt32LE(16 * 44100, 0x18); vgm.set(commands, 256);
  return {vgm, vgz:gzipSync(vgm), sample};
}
module.exports = {createOpnaFixture};
