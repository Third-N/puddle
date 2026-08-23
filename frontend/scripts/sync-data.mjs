/**
 * バックエンドの生成済みデータを、静的サイト用に public/data へ複製する。
 *
 *   node scripts/sync-data.mjs
 *
 * 静的版はブラウザ側で経路探索を行うため、これらのファイルを配信物に含める。
 * 複製なので public/data は git 管理しない。作り直すときは
 * backend/scripts/build_data.py を先に実行する。
 */
import { cp, mkdir, stat } from 'node:fs/promises';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const here = dirname(fileURLToPath(import.meta.url));
const source = join(here, '..', '..', 'backend', 'data', 'generated');
const target = join(here, '..', 'public', 'data');

const FILES = ['engine.json', 'walk_graph.json', 'hazards.geojson', 'places.json'];

await mkdir(target, { recursive: true });

let total = 0;
for (const name of FILES) {
  const from = join(source, name);
  try {
    const info = await stat(from);
    await cp(from, join(target, name));
    total += info.size;
    console.log(`  ${name}  ${(info.size / 1024).toFixed(0)}KB`);
  } catch {
    console.error(
      `${name} が見つかりません。backend で python scripts/build_data.py を実行してください`,
    );
    process.exit(1);
  }
}
console.log(`public/data へ複製しました（合計 ${(total / 1024 / 1024).toFixed(2)}MB）`);
