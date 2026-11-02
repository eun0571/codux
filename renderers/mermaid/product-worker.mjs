// Packaged Codux image worker. Uses the same isolated Mermaid 12 DOM renderer as
// the verified preview, without Python or the playground application.
import fs from 'node:fs/promises';
import {existsSync} from 'node:fs';
import path from 'node:path';
import os from 'node:os';
import http from 'node:http';
import readline from 'node:readline';
import {fileURLToPath} from 'node:url';
import {createHash} from 'node:crypto';
import {createRequire} from 'node:module';
const puppeteer = createRequire(import.meta.url)('puppeteer-core');

const root=path.dirname(fileURLToPath(import.meta.url));
const cache=path.resolve(process.argv[2]??path.join(root,'cache'));
let browser, server, baseUrl, profile;
console.log=(...args)=>console.error(...args);

export function horizontalSource(source) {
  const lines=source.split(/(?<=\n)/);
  let offset=0, front=false, directive=false, first=true;
  for(const line of lines) {
    const trimmed=line.trim();
    if(first&&trimmed==='---'){front=true;first=false;}
    else if(front){if(trimmed==='---')front=false;}
    else if(directive){if(trimmed.includes('}%%'))directive=false;}
    else if(!trimmed){}
    else if(trimmed.startsWith('%%')){if(trimmed.startsWith('%%{')&&!trimmed.includes('}%%'))directive=true;}
    else {
      const match=/^([ \t]*(?:flowchart|graph)[ \t]+)(TB|TD)(?=[ \t;\r\n]|$)/.exec(line);
      return match?source.slice(0,offset)+line.replace(match[0],match[1]+'LR')+source.slice(offset+line.length):source;
    }
    offset+=line.length;
  }
  return source;
}

async function start() {
  if(browser?.connected)return;
  server=http.createServer(async(req,res)=>{
    try {
      if(req.headers.host!==new URL(baseUrl).host){res.writeHead(403).end();return;}
      const routes={'/mermaid-frame.html':'frame.html','/mermaid-frame.js':'frame.js','/official-config.mjs':'official-config.mjs'};
      if(req.url==='/api/mermaid-runtime'){res.setHeader('Content-Type','application/json');res.end('{"version":"12.2.0","modernThemes":true}');return;}
      let file;
      if(routes[req.url])file=path.join(root,routes[req.url]);
      else if(req.url.startsWith('/vendor/mermaid/')) {
        const relative=decodeURIComponent(req.url.slice('/vendor/mermaid/'.length));
        file=path.resolve(root,'live-dist',relative);
        if(!file.startsWith(path.join(root,'live-dist')+path.sep)||!/\.(?:m?js|css|woff2)$/.test(file)){res.writeHead(404).end();return;}
      } else {res.writeHead(404).end();return;}
      res.setHeader('Content-Security-Policy',"default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; connect-src 'self'; frame-ancestors 'none'");
      res.setHeader('Content-Type',file.endsWith('.html')?'text/html':file.endsWith('.css')?'text/css':file.endsWith('.woff2')?'font/woff2':'text/javascript');
      res.end(await fs.readFile(file));
    } catch {res.writeHead(404).end();}
  });
  await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
  baseUrl=`http://127.0.0.1:${server.address().port}`;
  const executablePath=[process.env.CODUX_MERMAID_BROWSER,
    ...[process.env.PROGRAMFILES,process.env['PROGRAMFILES(X86)'],process.env.LOCALAPPDATA].filter(Boolean)
      .flatMap(base=>[path.join(base,'Google/Chrome/Application/chrome.exe'),path.join(base,'Microsoft/Edge/Application/msedge.exe')]),
    '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
    '/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge',
    '/usr/bin/google-chrome','/usr/bin/google-chrome-stable','/usr/bin/chromium','/usr/bin/chromium-browser','/usr/bin/microsoft-edge',
  ].find(p=>p&&path.isAbsolute(p)&&existsSync(p));
  if(!executablePath)throw Error('Chrome or Edge is unavailable; install a browser or set CODUX_MERMAID_BROWSER.');
  profile=await fs.mkdtemp(path.join(os.tmpdir(),'codux-diagram-'));
  browser=await puppeteer.launch({executablePath,headless:true,pipe:true,userDataDir:profile,timeout:15000,
    args:['--disable-background-networking','--disable-extensions','--no-first-run']});
}
async function close() {
  if(browser)await browser.close().catch(()=>{});
  browser=undefined;
  if(server)await new Promise(resolve=>server.close(resolve));
  server=undefined;
  if(profile)await fs.rm(profile,{recursive:true,force:true}).catch(()=>{});
  profile=undefined;
}
async function render(request) {
  if(typeof request.source!=='string'||!request.source.trim()||Buffer.byteLength(request.source)>16384)throw Error('Diagram must contain 1..16384 bytes.');
  const background=request.background;
  if(!/^#[0-9a-f]{6}$/i.test(background))throw Error('Invalid background');
  const rgb=[1,3,5].map(i=>parseInt(background.slice(i,i+2),16));
  const theme=rgb[0]*.2126+rgb[1]*.7152+rgb[2]*.0722<140?'redux-dark-color':'redux-color';
  const source=horizontalSource(request.source);
  const key=createHash('sha256').update(JSON.stringify(['codux-live12-v3',source,background,theme])).digest('hex');
  await fs.mkdir(cache,{recursive:true});
  const png=path.join(cache,key+'.png'), svg=path.join(cache,key+'.svg');
  if(existsSync(png)&&existsSync(svg))return {ok:true,png,svg,scale:2};
  await start();
  const page=await browser.newPage();
  try {
    await page.setViewport({width:1600,height:1200,deviceScaleFactor:1});
    await page.goto(baseUrl+'/mermaid-frame.html',{waitUntil:'networkidle0',timeout:10000});
    await page.waitForFunction(()=>typeof window.renderMermaidPreview==='function',{timeout:10000});
    const result=await page.evaluate(async({source,theme,background})=>{
      const result=await window.renderMermaidPreview(source,{config:{theme},backgroundMode:'custom',background},1);
      // Capture at 2x density for sharpness; Rust controls the displayed size
      // separately using the scale metadata returned with the PNG.
      window.scaleMermaidPreview(2);
      document.body.style.backgroundColor=background;
      return {...result,width:Math.ceil(result.width*2),height:Math.ceil(result.height*2)};
    },{source,theme,background});
    if(result.width>8192||result.height>8192||result.width*result.height>16000000)throw Error('Diagram exceeds image size limit.');
    const element=await page.$('#diagram > svg');
    const image=await element.screenshot();
    await fs.writeFile(png+'.tmp',image);
    await fs.writeFile(svg+'.tmp',result.svg,'utf8');
    await fs.rename(png+'.tmp',png);await fs.rename(svg+'.tmp',svg);
    return {ok:true,png,svg,scale:2};
  } finally {await page.close();}
}
async function main() {
  for await(const line of readline.createInterface({input:process.stdin})) {
    let timer;
    try {
      const result=await Promise.race([render(JSON.parse(line)),new Promise((_,reject)=>{timer=setTimeout(()=>reject(Error('Diagram rendering timed out.')),30000);})]);
      process.stdout.write(JSON.stringify(result)+'\n');
    } catch(error){await close();process.stdout.write(JSON.stringify({ok:false,error:String(error.message).slice(0,400)})+'\n');}
    finally {clearTimeout(timer);}
  }
  await close();
}
if(process.argv[1]&&path.resolve(process.argv[1])===fileURLToPath(import.meta.url))main().catch(async error=>{console.error(error);await close();process.exitCode=1;});
