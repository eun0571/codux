// Shared by the npm launcher and the native background update check.
import fs from 'node:fs';
import path from 'node:path';
import os from 'node:os';
import {fileURLToPath} from 'node:url';
import {execFileSync, spawnSync} from 'node:child_process';

export const PACKAGE = /^(?:@[a-z0-9][a-z0-9._-]*\/)?[a-z0-9][a-z0-9._-]*$/;
export function compareVersions(a, b) {
  const parse = value => {
    const match = /^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(?:-([a-z0-9.-]+))?$/.exec(value);
    if (!match) throw new Error('Invalid npm release version.');
    return {core: match.slice(1, 4).map(BigInt), pre: match[4]?.split('.')};
  };
  const left = parse(a), right = parse(b);
  for (let i = 0; i < 3; i++) if (left.core[i] !== right.core[i]) return left.core[i] > right.core[i] ? 1 : -1;
  if (!left.pre || !right.pre) return left.pre ? -1 : right.pre ? 1 : 0;
  for (let i = 0; i < Math.max(left.pre.length, right.pre.length); i++) {
    const x = left.pre[i], y = right.pre[i];
    if (x === y) continue;
    if (x === undefined || y === undefined) return x === undefined ? -1 : 1;
    const xn = /^\d+$/.test(x), yn = /^\d+$/.test(y);
    if (xn && yn) return BigInt(x) > BigInt(y) ? 1 : -1;
    if (xn !== yn) return xn ? -1 : 1;
    return x > y ? 1 : -1;
  }
  return 0;
}
export function metadata(root) {
  const value = JSON.parse(fs.readFileSync(path.join(root, 'codux-npm.json'), 'utf8'));
  if (!PACKAGE.test(value.package) || !PACKAGE.test(value.native_package)
      || !/^[a-z][a-z0-9-]*$/.test(value.tag) || !/^\d+\.\d+\.\d+(?:-[a-z0-9.-]+)?$/.test(value.version)) {
    throw new Error('Invalid Codux npm installation metadata.');
  }
  return value;
}

export function npmCli(env = process.env, node = process.execPath) {
  const candidates = [env.npm_execpath, path.join(path.dirname(node), 'node_modules/npm/bin/npm-cli.js')];
  for (const directory of (env.PATH || env.Path || '').split(path.delimiter).filter(path.isAbsolute)) {
    candidates.push(path.join(directory, 'node_modules/npm/bin/npm-cli.js'));
    const executable = path.join(directory, process.platform === 'win32' ? 'npm.cmd' : 'npm');
    try { candidates.push(fs.realpathSync(executable)); } catch {}
  }
  const found = candidates.find(candidate => candidate && path.isAbsolute(candidate)
    && path.basename(candidate) === 'npm-cli.js' && fs.existsSync(candidate));
  if (!found) throw new Error('Cannot find npm. Install Node.js with npm, then retry.');
  return found;
}

export function readNpm(args, cli = npmCli()) {
  return execFileSync(process.execPath, [cli, ...args], {
    cwd: os.tmpdir(), encoding: 'utf8', timeout: 20000, maxBuffer: 4 * 1024 * 1024,
    windowsHide: true, stdio: ['ignore', 'pipe', 'pipe'],
  }).trim();
}

export function selectVersion(info, value) {
  if (info.name !== value.package || !/^\d+\.\d+\.\d+(?:-[a-z0-9.-]+)?$/.test(info.version)
      || info.optionalDependencies?.[value.native_package] !== info.version) {
    throw new Error('No complete npm release for this platform is available.');
  }
  return info.version;
}

export function check(root, read = readNpm) {
  const value = metadata(root);
  const info = JSON.parse(read(['view', `${value.package}@${value.tag}`, '--json']));
  return {version: selectVersion(info, value)};
}

export function update(root, launcherDirectory) {
  const value = metadata(root);
  const cli = npmCli();
  const globalRoot = readNpm(['root', '-g'], cli);
  const installed = path.join(globalRoot, ...value.package.split('/'));
  if (!fs.existsSync(installed) || fs.realpathSync(installed) !== fs.realpathSync(launcherDirectory)) {
    throw new Error(`This is not npm's current global installation. Update it with npm install ${value.package}@${value.tag} using its original prefix.`);
  }
  const latest = check(root, args => readNpm(args, cli)).version;
  if (compareVersions(latest, value.version) <= 0) { console.log(`Codux ${value.version} is up to date.`); return 0; }
  // Delegate version ordering and integrity checks to npm; never overwrite npm folders ourselves.
  console.log(`Updating Codux ${value.version} to ${latest} through npm. Close other Codux sessions first.`);
  const result = spawnSync(process.execPath, [cli, 'install', '-g', `${value.package}@${latest}`], {cwd: os.tmpdir(), stdio: 'inherit'});
  if (result.error) throw result.error;
  if (result.status !== 0) throw new Error(`npm update failed. Close Codux sessions and its background server, then retry npm install -g ${value.package}@${value.tag}.`);
  return 0;
}

if (process.argv[1] && fs.realpathSync(process.argv[1]) === fileURLToPath(import.meta.url)) {
  try {
    if (process.argv[2] !== '--check' || process.argv.length !== 4) throw new Error('Expected --check <native package root>.');
    console.log(JSON.stringify(check(path.resolve(process.argv[3]))));
  } catch (error) {
    // npm remains responsible for registry credentials; do not relay its raw error output.
    console.error('Codux npm update check failed. Run codux update for installation guidance.');
    process.exitCode = 1;
  }
}
