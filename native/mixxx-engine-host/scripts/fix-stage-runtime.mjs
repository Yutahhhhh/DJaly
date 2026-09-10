import { readdir, open, realpath, access, cp, writeFile } from 'node:fs/promises';
import { execFileSync } from 'node:child_process';
import path from 'node:path';
import assert from 'node:assert/strict';

const bundle = path.resolve(process.argv[2]);
const stageRoot = path.resolve(import.meta.dirname, '../stage');
const relativeBundle = path.relative(stageRoot, bundle);
assert(relativeBundle === 'PlumdeckMixxxHost.app' || /^\.staging\.[^/]+\/PlumdeckMixxxHost\.app$/.test(relativeBundle), 'Only this generated staging bundle may be modified');
const frameworks = path.join(bundle, 'Contents/Frameworks');
const external = value => value.startsWith('/opt/homebrew/') || value.startsWith('/usr/local/');
const exists = async file => { try { await access(file); return true; } catch { return false; } };
const run = (command, args) => execFileSync(command, args, { encoding: 'utf8', stdio: ['ignore', 'pipe', 'pipe'] });
async function filesIn(directory) {
  const files = [];
  for (const item of await readdir(directory, { withFileTypes: true })) {
    const file = path.join(directory, item.name);
    if (item.isDirectory()) files.push(...await filesIn(file));
    else if (item.isFile()) {
      const handle = await open(file); const magic = Buffer.alloc(4); await handle.read(magic, 0, 4, 0); await handle.close();
      if ([0xfeedfacf, 0xfeedface, 0xcafebabe, 0xbebafeca].includes(magic.readUInt32LE())) files.push(file);
    }
  }
  return files;
}
function dependencies(file) {
  return run('otool', ['-L', file]).split('\n').slice(1).filter(line => line.startsWith('\t')).map(line => line.trim().split(' (')[0]);
}
function rpaths(file) {
  return [...run('otool', ['-l', file]).matchAll(/cmd LC_RPATH\s+cmdsize \d+\s+path (.*?) \(offset/g)].map(match => match[1]);
}
const changes = [];
let files = await filesIn(bundle);
for (let index = 0; index < files.length; index++) {
  const file = files[index];
  const id = run('otool', ['-D', file]).split('\n')[1]?.trim();
  if (id && external(id)) {
    const replacement = '@rpath/' + path.relative(frameworks, file);
    run('install_name_tool', ['-id', replacement, file]); changes.push({ file: path.relative(bundle, file), id, replacement });
  }
  for (const dependency of dependencies(file)) {
    if (!external(dependency)) continue;
    const framework = dependency.match(/([^/]+\.framework\/.*)$/)?.[1];
    let target = path.join(frameworks, framework || path.basename(dependency));
    if (!await exists(target)) {
      const source = await realpath(dependency);
      target = path.join(frameworks, framework || path.basename(source));
      if (!await exists(target)) {
        if (framework) {
          const sourceBundle = dependency.slice(0, dependency.indexOf('.framework/') + '.framework'.length);
          await cp(sourceBundle, path.join(frameworks, path.basename(sourceBundle)), { recursive: true });
        } else await cp(source, target);
        const refreshed = await filesIn(bundle);
        for (const discovered of refreshed) if (!files.includes(discovered)) files.push(discovered);
      }
    }
    const replacement = '@loader_path/' + path.relative(path.dirname(file), target);
    run('install_name_tool', ['-change', dependency, replacement, file]); changes.push({ file: path.relative(bundle, file), dependency, replacement });
  }
  for (const rpath of rpaths(file)) if (external(rpath)) {
    run('install_name_tool', ['-delete_rpath', rpath, file]); changes.push({ file: path.relative(bundle, file), removedRpath: rpath });
  }
}
const unresolved = [];
for (const file of files) for (const item of [...dependencies(file), ...rpaths(file)]) if (external(item)) unresolved.push({ file, item });
assert.deepEqual(unresolved, [], 'Staged Mach-O still refers to an external Homebrew runtime');
await writeFile(path.join(bundle, '../runtime-audit.json'), JSON.stringify({ machOFiles: files.length, unresolved, changes }, null, 2));
console.log(`Runtime audit: ${files.length} Mach-O files, ${changes.length} corrections, zero external Homebrew references.`);
