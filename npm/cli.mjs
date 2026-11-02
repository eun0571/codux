#!/usr/bin/env node
// npm owns installation files; the native binary owns the terminal and conversation.
import fs from 'node:fs';
import path from 'node:path';
import {createRequire} from 'node:module';
import {fileURLToPath} from 'node:url';
import {spawn} from 'node:child_process';
import {update} from './update.mjs';

export function platformPackage(metadata, platform = process.platform, arch = process.arch) {
  const name = metadata.codux.platforms[`${platform}-${arch}`];
  if (!name) throw new Error(`Codux has no verified build for ${platform}-${arch} in this release.`);
  if (platform === 'linux' && !process.report.getReport().header.glibcVersionRuntime) {
    throw new Error('This Codux Linux build requires glibc; Alpine/musl is not supported.');
  }
  return name;
}

export async function main(args = process.argv.slice(2)) {
  const directory = path.dirname(fileURLToPath(import.meta.url));
  const metadata = JSON.parse(fs.readFileSync(path.join(directory, 'package.json'), 'utf8'));
  const name = platformPackage(metadata);
  let native;
  try { native = createRequire(import.meta.url).resolve(`${name}/package.json`); }
  catch { throw new Error(`Missing ${name}. Reinstall ${metadata.name} with optional dependencies enabled.`); }
  const nativeMetadata = JSON.parse(fs.readFileSync(native, 'utf8'));
  if (nativeMetadata.version !== metadata.version) throw new Error('Codux package versions differ. Reinstall the npm package.');
  const root = fs.realpathSync(path.join(path.dirname(native), 'runtime'));
  if (args.length === 1 && args[0] === 'update') return update(root, directory);
  const executable = path.join(root, 'bin', process.platform === 'win32' ? 'codux.exe' : 'codux');
  const child = spawn(executable, args, {
    stdio: 'inherit',
    env: {...process.env, CODUX_NODE: process.execPath, CODUX_NPM_ROOT: root},
  });
  const forward = signal => { if (!child.killed) child.kill(signal); };
  const handlers = ['SIGINT', 'SIGTERM'].map(signal => {
    const handler = () => forward(signal);
    process.on(signal, handler);
    return [signal, handler];
  });
  const result = await new Promise((resolve, reject) => {
    child.once('error', reject);
    child.once('exit', (code, signal) => resolve({code, signal}));
  }).finally(() => handlers.forEach(([signal, handler]) => process.off(signal, handler)));
  // Only our native update action returns this handoff code. No executable is open now.
  if (result.code === 85) return update(root, directory);
  if (result.signal) { process.kill(process.pid, result.signal); return 1; }
  return result.code ?? 1;
}

if (process.argv[1] && fs.realpathSync(process.argv[1]) === fileURLToPath(import.meta.url)) {
  main().then(code => { process.exitCode = code; }).catch(error => {
    console.error(`Codux: ${error.message}`);
    process.exitCode = 1;
  });
}
