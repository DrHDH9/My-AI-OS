// 把 DSH 的多帧 zstd 会话文件解成明文 jsonl
// 用法: node zstd2jsonl.js <in.zstd> <out.jsonl>
const fs = require("fs");
const zlib = require("zlib");

const src = process.argv[2];
const dst = process.argv[3];
const buf = fs.readFileSync(src);

// zstd 帧魔数 28 B5 2F FD，DSH 一个会话文件里有多帧
const magic = Buffer.from([0x28, 0xb5, 0x2f, 0xfd]);
const cuts = [];
for (let i = 0; i + 3 < buf.length; i++) {
  if (buf[i] === magic[0] && buf[i + 1] === magic[1] && buf[i + 2] === magic[2] && buf[i + 3] === magic[3]) {
    cuts.push(i);
  }
}
cuts.push(buf.length);

const parts = [];
let ok = 0,
  bad = 0;
for (let i = 0; i < cuts.length - 1; i++) {
  const piece = buf.subarray(cuts[i], cuts[i + 1]);
  try {
    parts.push(zlib.zstdDecompressSync(piece).toString("utf8"));
    ok++;
  } catch (e) {
    bad++;
  }
}
fs.writeFileSync(dst, parts.join(""));
console.log(`frames=${ok} failed=${bad} bytes=${buf.length} -> ${dst}`);
