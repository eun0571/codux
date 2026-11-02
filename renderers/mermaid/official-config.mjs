// Shared by the browser playground and the terminal renderer.
export function officialConfig(options = {}, terminalBackground) {
  const theme = options.officialTheme ?? 'default';
  const themes = ['default','dark','neutral','forest','base','neo','neo-dark','redux','redux-dark','redux-color','redux-dark-color'];
  if (!themes.includes(theme)) throw Error('Invalid Mermaid theme');
  const fontFamily = options.font ?? 'trebuchet ms, verdana, arial, sans-serif';
  if (!/^[a-zA-Z0-9 ,'-]{1,160}$/.test(fontFamily)) throw Error('Invalid font');
  const flowchart = {useMaxWidth:false, htmlLabels:true};
  for (const [key, value] of Object.entries({nodeSpacing:50, rankSpacing:50, padding:15})) {
    flowchart[key] = options[key] ?? value;
    if (!Number.isInteger(flowchart[key]) || flowchart[key] < 0 || flowchart[key] > 200) throw Error(`Invalid ${key}`);
  }
  const curve = options.curve ?? 'basis';
  if (!['basis','linear','step','stepBefore','stepAfter','monotoneX'].includes(curve)) throw Error('Invalid curve');
  flowchart.curve = curve;
  const background = terminalBackground ?? options.background ?? '#ffffff';
  if (!/^#[0-9a-f]{6}$/i.test(background)) throw Error('Invalid background');
  if (options.backgroundMode !== undefined && !['transparent','custom','theme'].includes(options.backgroundMode)) throw Error('Invalid background mode');
  const custom = options.config ?? {};
  if (!custom || typeof custom !== 'object' || Array.isArray(custom)) throw Error('Mermaid config must be a JSON object');
  function check(value) {
    if(value && typeof value==='object')for(const [key,child] of Object.entries(value)) {
      if(['__proto__','prototype','constructor'].includes(key))throw Error('Invalid config key');
      check(child);
    }
  }
  check(custom);
  const config = {theme, fontFamily, flowchart, ...custom};
  if (!themes.includes(config.theme)) throw Error('Invalid Mermaid theme in config');
  config.flowchart = {...flowchart,...custom.flowchart};
  // User config controls appearance, never script execution or resource limits.
  Object.assign(config,{startOnLoad:false,securityLevel:'strict',maxTextSize:16384,maxEdges:1000,
    secure:['secure','securityLevel','startOnLoad','maxTextSize','maxEdges','suppressErrorRendering']});
  return {
    config,
    background: terminalBackground || options.backgroundMode === 'custom' ? background : 'transparent'
  };
}
