import {officialConfig} from '/official-config.mjs';

let renderer, queue=Promise.resolve(), dimensions={width:800,height:500};
const host=document.getElementById('diagram');
window.scaleMermaidPreview=scale=>{
  const svg=host.querySelector('svg');
  if(svg){svg.style.width=`${dimensions.width*scale}px`;svg.style.height=`${dimensions.height*scale}px`;}
};
window.renderMermaidPreview=(source,options,revision)=> {
  const job=queue.then(async()=>{
    renderer ??= import('/vendor/mermaid/mermaid.esm.min.mjs');
    const mermaid=(await renderer).default;
    const runtime=await (await fetch('/api/mermaid-runtime')).json();
    const {config,background}=officialConfig(options);
    if(!runtime.modernThemes && /^(redux|neo)/.test(config.theme))
      throw Error('This theme needs Mermaid 12.2.0. Run scripts/setup-mermaid-live.ps1 and restart the playground.');
    // Layout measurement and final display share this document, without the
    // editor's global p/span/box-sizing styles affecting labels.
    host.replaceChildren();
    mermaid.initialize(config);
    await document.fonts.ready;
    const {svg}=await mermaid.render(`official-diagram-${revision}`,source,host);
    host.innerHTML=svg;
    const root=host.querySelector('svg');
    if(!root)throw Error('Mermaid returned no SVG.');
    if(background!=='transparent')root.style.backgroundColor=background;
    const box=root.viewBox.baseVal;
    const width=box.width||root.getBoundingClientRect().width;
    const height=box.height||root.getBoundingClientRect().height;
    if(!Number.isFinite(width)||!Number.isFinite(height)||width<=0||height<=0)throw Error('Invalid SVG dimensions.');
    dimensions={width:Math.ceil(width),height:Math.ceil(height)};
    window.scaleMermaidPreview(1);
    const serialized=new XMLSerializer().serializeToString(root);
    // HTML parsing above normalizes <br> inside foreignObject to valid XHTML
    // before SVG export. Never parse the renderer's raw HTML string as XML.
    if(new DOMParser().parseFromString(serialized,'image/svg+xml').querySelector('parsererror'))
      throw Error('SVG export contains invalid XML.');
    return {svg:serialized,...dimensions,version:runtime.version,theme:config.theme};
  });
  queue=job.catch(()=>{});
  return job;
};
