// JSON-lines text conversion. No browser, image protocol, or model call.
import * as beautiful from 'beautiful-mermaid';
import stringWidth from 'string-width';
import readline from 'node:readline';
import { pathToFileURL } from 'node:url';

const render = beautiful.renderMermaidASCII ?? beautiful.renderMermaidAscii;
const segmenter = new Intl.Segmenter('ko', {granularity: 'grapheme'});

// The renderer measures UTF-16 characters rather than terminal columns. Give
// non-ASCII graphemes one-cell placeholder units, then restore complete tokens.
// Nothing in the stored Mermaid source is changed.
export function encodeLabels(source) {
  const tokens = new Map();
  const reverse = new Map();
  let next = 0xe000;
  let encoded = '';
  for (const {segment} of segmenter.segment(source)) {
    if (/^[\x00-\x7f]+$/.test(segment)) { encoded += segment; continue; }
    let token = tokens.get(segment);
    if (!token) {
      const width = stringWidth(segment);
      if (width < 1 || width > 2 || next > 0xf8ff) throw new Error('Unsupported label character width.');
      token = String.fromCharCode(next++).repeat(width);
      tokens.set(segment, token);
      reverse.set(token, segment);
    }
    encoded += token;
  }
  return { encoded, restore(output) {
    for (const [token, original] of reverse) output = output.split(token).join(original);
    if (/[\ue000-\uf8ff]/.test(output)) throw new Error('Renderer split a label; original source retained.');
    return output;
  }};
}

export function renderText(request) {
  const source = request?.source;
  if (typeof source !== 'string' || !source.trim() || Buffer.byteLength(source) > 16384) {
    throw new Error('Text diagrams must contain 1..16384 bytes.');
  }
  if (/[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]/.test(source)) throw new Error('Control characters are not supported.');
  const columns = request.columns;
  if (!Number.isInteger(columns) || columns < 1 || columns > 240) throw new Error('Invalid terminal width.');
  const header = source.trim().split(/\r?\n|;/)[0].trim();
  if (!/^(?:graph|flowchart)\s+(?:LR|RL|TD|TB|BT)\b|^(?:stateDiagram(?:-v2)?|sequenceDiagram|classDiagram|erDiagram|xychart(?:-beta)?)\b/.test(header)) {
    throw new Error('This diagram type is not supported by beautiful-mermaid.');
  }
  // The pinned renderer treats RL as LR. Reject it instead of silently changing direction.
  if (/^(?:graph|flowchart)\s+RL\b/.test(header)) throw new Error('Right-to-left graphs are not supported by this text renderer.');
  // The library can silently accept A[broken as a bare A node. Catch incomplete
  // paired labels before conversion instead of presenting a misleading diagram.
  if (/^(?:graph|flowchart)\b/.test(header)) {
    for (const line of source.split(/\r?\n/)) {
      if (/^\s*%%/.test(line)) continue;
      const syntax = line.replace(/"[^"\n]*"/g, '""');
      for (const [open, close] of [['[', ']'], ['(', ')'], ['{', '}']]) {
        const opens = syntax.split(open).length - 1;
        const closes = syntax.split(close).length - 1;
        // Mermaid's asymmetric >label] shape has one unpaired closing bracket.
        const asymmetric = open === '[' ? (syntax.match(/[\w-]>[^\[\]]*\]/g)?.length ?? 0) : 0;
        if (opens + asymmetric !== closes) throw new Error('Unbalanced node label; original source retained.');
      }
    }
  }
  const labels = encodeLabels(source.trim());
  const options = {use_ascii: false, padding_x: 5, padding_y: 5, box_border_padding: 0,
    color_mode: 'none', theme: 'default', ...request.options};
  if (typeof options.use_ascii !== 'boolean' ||
      ![options.padding_x, options.padding_y].every(n => Number.isInteger(n) && n >= 1 && n <= 10) ||
      !Number.isInteger(options.box_border_padding) || options.box_border_padding < 0 || options.box_border_padding > 4 ||
      !['none', 'auto', 'ansi16', 'ansi256', 'truecolor'].includes(options.color_mode) ||
      !(options.theme === 'default' || Object.hasOwn(beautiful.THEMES, options.theme))) {
    throw new Error('Invalid text render options.');
  }
  const palette = beautiful.THEMES[options.theme];
  const theme = palette ? {fg: palette.fg, border: palette.border ?? palette.line ?? palette.fg,
    line: palette.line ?? palette.fg, arrow: palette.accent ?? palette.fg,
    corner: palette.line ?? palette.fg, junction: palette.border ?? palette.line ?? palette.fg,
    accent: palette.accent ?? palette.fg, bg: palette.bg} : undefined;
  const output = labels.restore(render(labels.encoded, { useAscii: options.use_ascii,
    colorMode: options.color_mode === 'auto' ? 'truecolor' : options.color_mode, theme,
    paddingX: options.padding_x, paddingY: options.padding_y, boxBorderPadding: options.box_border_padding
  })).replace(/\r\n/g, '\n').trimEnd();
  const plain = output.replace(/\x1b\[[0-9;]*m/g, '');
  if (!plain.trim() || /[\x00-\x09\x0b-\x1f\x7f-\x9f]/.test(plain)) throw new Error('Invalid text renderer output.');
  if (Buffer.byteLength(output) > 131072 || plain.split('\n').length > 160) throw new Error('Text diagram exceeds the preview size limit.');
  if (plain.split('\n').every(line => stringWidth(line) <= columns)) return {text: output};
  throw new Error(`Text diagram does not fit in ${columns} columns. Widen the terminal or reduce spacing.`);
}

async function main() {
  console.log = (...args) => console.error(...args);
  for await (const line of readline.createInterface({input: process.stdin, crlfDelay: Infinity})) {
    try {
      if (Buffer.byteLength(line) > 100000) throw new Error('Request is too large.');
      process.stdout.write(JSON.stringify({ok: true, ...renderText(JSON.parse(line))}) + '\n');
    } catch (error) {
      process.stdout.write(JSON.stringify({ok: false, error: String(error.message ?? error).slice(0, 300)}) + '\n');
    }
  }
}
if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  main().catch(error => { console.error(error); process.exitCode = 1; });
}
