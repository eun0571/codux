/* Browser UI settings. Only preferences, never session contents, are persisted. */
(() => {
  'use strict';
  const M=PlaygroundModel, $=selector=>document.querySelector(selector), palettes=PLAYGROUND_PALETTES;
  const local=window.PLAYGROUND_LOCAL;
  const storageKey=local?'codux.playground.local.v1':'codux.playground.v1';
  let syntax=palettes.find(p=>p.id==='catppuccin-mocha')||palettes[0], settings=M.copy(PLAYGROUND_DEFAULTS), terminalTone='dark';
  if(local&&M.validSettings(local.settings))settings={...settings,...M.migrate(local.settings)};
  try {
    const stored=JSON.parse(localStorage.getItem(storageKey));
    if(stored&&M.validSettings(stored.settings)){
      settings={...M.copy(PLAYGROUND_DEFAULTS),...M.migrate(stored.settings)};
      terminalTone=stored.terminalTone==='light'?'light':'dark';
    }
  } catch (_) {}
  let stack=[],entries=[],cursor=0,field=false,viewer,statusFrameId=null,lastStatusPaint=0;
  const reducedMotion=window.matchMedia?.('(prefers-reduced-motion: reduce)')||{matches:false,addEventListener(){}};
  const cursors=new Map();
  function say(message){$('#announcement').textContent=message;}
  function persist(){try{localStorage.setItem(storageKey,JSON.stringify({settings,terminalTone}));}
    catch(_){say('Storage unavailable · settings kept in this tab.');}}
  function node(tag,className,text){const n=document.createElement(tag);if(className)n.className=className;if(text!==undefined)n.textContent=text;return n;}
  const rgb=value=>`rgb(${value.join(',')})`;
  const outer=()=>terminalTone==='light'?[245,245,245]:[24,24,24];
  function background(value){return value==='none'?'transparent':rgb(M.surface(value,outer()));}
  function render(){
    viewer?.render();
    const preview=$('#animation-preview'),wasHidden=preview.hidden;preview.hidden=current()?.page!=='animation';
    if(wasHidden&&!preview.hidden)preview.dataset.startedAt=String(performance.now());
    syncStatusAnimation();
  }
  function paintStatus(now){
    let active=false;
    for(const surface of [$('#animation-preview'),$('#working-preview')]){
      if(surface.hidden)continue;
      const completed=surface.dataset.state==='worked',animated=!reducedMotion.matches;
      const frame=M.statusFrame(settings,outer(),terminalTone==='light'?[36,36,36]:[230,230,230],now-Number(surface.dataset.startedAt||now),{animated,completed});
      surface.style.background=rgb(frame.background);surface.style.color=rgb(frame.foreground);
      const dot=surface.querySelector('.status-dot'),label=surface.querySelector('.working-label');dot.hidden=completed||!animated;dot.style.color=rgb(frame.bullet);
      if(!completed){
        if(label.dataset.shimmer!=='true'){label.replaceChildren(...Array.from('Working',letter=>node('span','',letter)));label.dataset.shimmer='true';}
        [...label.children].forEach((letter,i)=>{letter.style.color=rgb(frame.letters[i]);});
        active ||= animated;
      }
    }
    return active;
  }
  function statusTick(now){
    statusFrameId=null;if(document.hidden)return;
    if(now-lastStatusPaint<32){statusFrameId=requestAnimationFrame(statusTick);return;}
    lastStatusPaint=now;if(paintStatus(now))statusFrameId=requestAnimationFrame(statusTick);
  }
  function syncStatusAnimation(){
    if(statusFrameId!==null){cancelAnimationFrame(statusFrameId);statusFrameId=null;}
    if(!document.hidden&&paintStatus(performance.now()))statusFrameId=requestAnimationFrame(statusTick);
  }
  reducedMotion.addEventListener('change',syncStatusAnimation);
  document.addEventListener('visibilitychange',syncStatusAnimation);
  function setSyntax(){
    syntax=palettes.find(p=>p.light===(terminalTone==='light')&&(terminalTone==='light'||p.id==='catppuccin-mocha'))||palettes.find(p=>p.light===(terminalTone==='light'))||palettes[0];
    const terminal=$('.terminal');terminal.style.colorScheme=terminalTone;terminal.style.setProperty('--base',rgb(outer()));
    terminal.style.setProperty('--fg',terminalTone==='light'?'#242424':'#e6e6e6');
    terminal.style.setProperty('--muted',terminalTone==='light'?'#666666':'#a0a0af');
    for(const [key,index]of[['function',0],['keyword',1],['string',2]])terminal.style.setProperty(`--${key}`,rgb(syntax.accents[index]));
    viewer?.setOuter(outer());render();
  }
  const current = () => stack.at(-1);
  function open(page, title, role, key) {
    if (current()) cursors.set(current().page,cursor);
    const inherited=current()?.role===role&&current()?.targets;
    stack.push({page,title,role,key,targets:inherited?[...inherited]:role?[role]:[],before:M.copy(settings),values:false});
    $('#menu').hidden = false; showPage();
  }
  function back(commit = false) {
    if (!current()) return;
    const previous = stack.pop(); cursors.set(previous.page,cursor);
    if (!commit && previous.values) settings = previous.before;
    render();
    if (stack.length) showPage();
    else { $('#menu').hidden = true; $('#command-input').focus(); }
  }
  function close() { while (stack.length) back(); }
  function chooseEntry(index, focus = true) {
    if (entries[index]?.disabled) return;
    cursor = index;
    for (const [i, button] of [...$('#menu-content').querySelectorAll('.menu-item')].entries()) {
      button.setAttribute('aria-current',String(i === cursor));
      button.tabIndex = i === cursor ? 0 : -1;
      if (i === cursor && focus) {
        button.focus({preventScroll:true});
        const container=$('#menu-content'), top=button.offsetTop-container.offsetTop;
        if(top<container.scrollTop)container.scrollTop=top;
        else if(top+button.offsetHeight>container.scrollTop+container.clientHeight)container.scrollTop=top+button.offsetHeight-container.clientHeight;
      }
    }
    if (entries[index]?.preview) { settings = entries[index].preview(); render(); }
    else if (current()?.values) {settings = M.copy(current().before);render();}
  }
  function change(key,value) {return M.applyCardValue(current().before,current().targets,key==='expandable-value'?'expandable':key,value);}
  function scopedPage(p){return p?.role&&p.key&&!p.key.startsWith('hex:')&&p.page!=='apply-targets'&&p.page!=='choose-targets';}
  function scopeControl(){
    const p=current();if(!scopedPage(p))return;
    const button=node('button','apply-scope',`Apply to: ${M.targetLabel(p.targets,p.role)} ›`);button.type='button';
    button.title=p.targets.map(role=>M.roleLabels[role]).join(', ');
    button.addEventListener('click',()=>{if(!p.values)p.before=M.copy(settings);settings=M.copy(p.before);render();open('apply-targets','Apply to',p.role);});
    $('#menu-content').prepend(button);
  }
  function useTargets(targets){
    if(!targets.length)return;
    while(['apply-targets','choose-targets'].includes(current()?.page))stack.pop();
    for(let i=stack.length-1;i>=0&&stack[i].key&&stack[i].role===current().role;i--)stack[i].targets=[...targets];
    settings=M.copy(current().before);showPage();
  }
  function rows(list) {
    entries = list; field = false;
    const container = $('#menu-content'); container.replaceChildren();
    list.forEach((entry,index) => {
      const button = node('button','menu-item'); button.type='button'; button.disabled=!!entry.disabled;
      button.append(node('span','menu-label',entry.label));
      if (entry.colors) {const swatches = node('span','swatches'); for (const c of entry.colors) {const swatch=node('i');swatch.style.background=background(c.background);swatches.append(swatch);}button.append(swatches);}
      if (entry.detail) button.append(node('span','menu-detail',entry.detail));
      if (entry.description) button.title = entry.description;
      button.addEventListener('mouseenter',() => chooseEntry(index,false));
      button.addEventListener('focus',() => {if(cursor !== index)chooseEntry(index,false);});
      button.addEventListener('click',() => {chooseEntry(index,false);entry.action?.();});
      container.append(button);
    });
    let index = Math.min(cursors.get(current().page) || 0,list.length-1);
    if (list[index]?.disabled) index=list.findIndex(item=>!item.disabled);
    chooseEntry(index);
    scopeControl();
  }
  function navigation(label, page, role, key) {return {label,detail:'›',action:()=>open(page,label,role,key)};}
  function values(options) {
    current().values = true;
    const p=current(), key=p.key==='expandable-value'?'expandable':p.key;
    if(!cursors.has(p.page))cursors.set(p.page,Math.max(0,options.findIndex(([,value])=>value===M.card(p.before,p.role)[key])));
    rows(options.map(([label,value])=>({label,preview:()=>change(current().key,value),action:()=>{persist();back(true);}})));
  }
  function inputForm(label,initial,save,preview) {
    field = true; entries=[];
    const form=node('form','field-form'), caption=node('label','',label), input=node('input');
    input.value=initial;input.maxLength=100;input.setAttribute('aria-label',label);
    const submit=node('button','','Save');submit.type='submit';
    form.append(caption,input,submit,node('p','','Enter to save · Esc to cancel'));
    input.addEventListener('input',()=>{if(preview){preview(input.value);render();}});
    form.addEventListener('submit',e=>{e.preventDefault();try{save(input.value);}catch(error){say(error.message);}});
    $('#menu-content').replaceChildren(form);scopeControl();input.focus();
  }
  function showPage() {
    const p=current(); $('#menu-title').textContent=`Custom UI${p.page==='root'?'':` / ${p.title}`}`;
    if(p.page==='apply-targets')rows([
      {label:'Current card',detail:M.roleLabels[p.role],action:()=>useTargets([p.role])},
      {label:'Selected cards…',detail:p.targets.map(role=>M.roleLabels[role]).join(', '),action:()=>open('choose-targets','Select cards',p.role)},
      {label:'All cards',detail:'All five card types',action:()=>useTargets(M.roles)}]);
    else if(p.page==='choose-targets')rows([
      {label:'Use selected cards',detail:`${p.targets.length} selected`,disabled:!p.targets.length,action:()=>useTargets(p.targets)},
      ...M.roles.map(role=>({label:`${p.targets.includes(role)?'☑':'☐'} ${M.roleLabels[role]}`,action:()=>{
        p.targets=p.targets.includes(role)?p.targets.filter(r=>r!==role):[...p.targets,role];cursors.set(p.page,cursor);showPage();}}))]);
    else if (p.page==='root') rows([
      navigation('Theme','theme'),
      navigation('Question','question-group'),navigation('Tools','card:tools','tools'),navigation('Answer','answer-group'),
      {...navigation('Card display','card-display'),detail:M.cardMode(settings)},navigation('Reset to defaults','reset')]);
    else if(p.page==='card-display'){
      p.values=true;
      const modes=[['0: Progress',false,true],['1: Answers only',false,false],['2: All cards',true,true]];
      if(!cursors.has(p.page))cursors.set(p.page,Math.max(0,modes.findIndex(([,tools,intermediate])=>tools===settings.show_tools&&intermediate===settings.show_intermediate)));
      rows(modes.map(([label,tools,intermediate])=>({label,preview:()=>({...M.copy(p.before),show_tools:tools,show_intermediate:intermediate}),action:()=>{persist();back(true);}})));
    }
    else if(p.page==='reset'){
      p.values=true;
      rows([{label:'Keep current settings',preview:()=>M.copy(p.before),action:()=>back()},
        {label:'Restore shipped defaults',preview:()=>M.copy(PLAYGROUND_DEFAULTS),action:()=>{persist();viewer.reset();back(true);say('Card settings reset to Codux defaults in this browser.');}}]);
    }
    else if (p.page==='question-group') rows([navigation('Prompt style','card:question','question'),navigation('Reply style','card:reply','reply')]);
    else if (p.page==='answer-group') rows([navigation('Final answer style','card:answer','answer'),navigation('Intermediate answer','card:intermediate','intermediate'),
      {label:'Mermaid',detail:'Terminal only',disabled:true,description:'Image protocols are not simulated in this card layout demo.'},navigation('Working animation','animation')]);
    else if (p.page==='animation') {
      p.values=true;
      const modes=['one_second','two_seconds','three_seconds','four_seconds'];
      if(!cursors.has(p.page))cursors.set(p.page,Math.max(0,modes.indexOf(settings.working_animation)));
      rows(modes.map((value,index)=>({label:`${index+1} second${index?'s':''}`,preview:()=>({...M.copy(p.before),working_animation:value}),action:()=>{persist();back(true);}})));
    }
    else if (p.page.startsWith('card:')) {
      const list=[];
      if (['tools','intermediate'].includes(p.role)) list.push(navigation('Display',`display:${p.role}`,p.role));
      for (const [label,key] of [['Expandable','expandable'],['Maximum width','max_width'],['Padding','padding'],['Background','background'],['Title','title']]) list.push(navigation(label,`element:${p.role}:${key}`,p.role,key));
      rows(list);
    } else if (p.page==='theme') {
      p.values=true; rows(syntax.choices.map(choice=>({label:choice.name,colors:choice.colors,description:choice.description,preview:()=>M.applyPalette(p.before,choice),action:()=>{persist();back(true);}})));
    } else if (p.page.startsWith('display:')) {
      p.values=true;if(!cursors.has(p.page))cursors.set(p.page,p.before[`show_${p.role}`]?0:1);
      rows([true,false].map(value=>({label:value?'Shown':'Hidden',preview:()=>({...M.copy(p.before),[`show_${p.role}`]:value}),action:()=>{persist();back(true);}})));
    } else if (p.key==='expandable') rows([navigation('Enabled',`value:${p.role}:enabled`,p.role,'enabled'),{...navigation('Initial state',`value:${p.role}:default_expanded`,p.role,'default_expanded'),disabled:!M.card(settings,p.role).expandable}]);
    else if (p.key==='enabled') {p.key='expandable-value'; values([['On',true],['Off',false]]);}
    else if (p.key==='expandable-value') values([['On',true],['Off',false]]);
    else if (p.key==='default_expanded') values([['Expanded',true],['Collapsed',false]]);
    else if (p.key==='max_width') values([50,60,70,80,100].map(n=>[`${n}%`,n]));
    else if (p.key==='padding') rows([navigation('Horizontal',`value:${p.role}:padding_x`,p.role,'padding_x'),navigation('Vertical',`value:${p.role}:padding_y`,p.role,'padding_y')]);
    else if (p.key==='padding_x') values([0,1,2,3,4,5,6].map(n=>[`${n} column${n===1?'':'s'}`,n]));
    else if (p.key==='padding_y') values([0,1,2,3,4,5,6].map(n=>[`${n/2} row${n===2?'':'s'}`,n]));
    else if (p.key==='title') rows([navigation('Show title',`value:${p.role}:title_visible`,p.role,'title_visible'),navigation('Title text',`text:${p.role}`,p.role,'title_text')]);
    else if (p.key==='title_visible') values([['Shown',true],['Hidden',false]]);
    else if (p.key==='title_text') {p.values=true;inputForm('Title (outside the background)',M.card(p.before,p.role).title,value=>{settings=change('title',value);persist();back(true);},value=>{settings=change('title',value);});}
    else if (p.key==='background') {
      p.values=true;
      if(!cursors.has(p.page))cursors.set(p.page,Math.max(0,M.colors.findIndex(([,value])=>JSON.stringify(value)===JSON.stringify(M.card(p.before,p.role)[p.key]))));
      rows([...M.colors.map(([label,value])=>({label,preview:()=>change(p.key,value),action:()=>{persist();back(true);}})),navigation('Custom HEX',`hex:${p.role}:${p.key}`,p.role,`hex:${p.key}`)]);
    } else if (p.key?.startsWith('hex:')) {
      const key=p.key.slice(4);p.values=true;
      const parse=value=>{if(!/^#[0-9a-f]{6}$/i.test(value))throw new Error('Enter a color in #RRGGBB format.');return {rgb:[1,3,5].map(i=>parseInt(value.slice(i,i+2),16))};};
      const value=M.card(p.before,p.role)[key], initial=value?.rgb?`#${value.rgb.map(c=>c.toString(16).padStart(2,'0')).join('')}`:'#404050';
      inputForm('#RRGGBB',initial,value=>{settings=change(key,parse(value));persist();const saved=M.copy(settings);back(true);back(true);settings=saved;render();},value=>{try{settings=change(key,parse(value));}catch(_){}});
    }
  }
  function openCustom() {if(viewer?.isWorking()){say('/custom is available after the Working preview finishes.');return;}if(!stack.length){cursors.clear();open('root','Custom UI');}else $('#menu-content .menu-item[aria-current=true], #menu-content input')?.focus();}

  viewer=createSessionViewer({getSettings:()=>settings,changeSettings:next=>{settings=next;persist();},say,openCustom,statusChanged:syncStatusAnimation});
  $('#back').addEventListener('click',()=>back());$('#close').addEventListener('click',close);
  document.addEventListener('pointerdown',event=>{if(stack.length&&!$('#menu').contains(event.target))close();});
  $('#menu').addEventListener('keydown',event=>{
    if(event.key==='Escape'){event.preventDefault();back();return;}
    if(field)return;
    if(event.target.classList.contains('apply-scope')){
      if(event.key==='ArrowDown'){event.preventDefault();chooseEntry(cursor);}return;
    }
    if(['ArrowDown','ArrowUp','Home','End'].includes(event.key)){
      if(event.key==='ArrowUp'&&cursor===0&&$('#menu-content .apply-scope')){event.preventDefault();$('#menu-content .apply-scope').focus();return;}
      event.preventDefault();let next=cursor,delta=event.key==='ArrowUp'?-1:1;
      if(event.key==='Home')next=-1;else if(event.key==='End'){next=entries.length;delta=-1;}
      for(let count=0;count<entries.length;count++){next=(next+delta+entries.length)%entries.length;if(!entries[next].disabled){chooseEntry(next);break;}}
    }
  });
  $('#version').textContent=`Preview ${PLAYGROUND_RELEASE.version}`;
  $('#version').title=`UI build target: Codux ${PLAYGROUND_RELEASE.version}, pinned Codex ${PLAYGROUND_RELEASE.upstream}. No CLI process is running in this page.`;
  setSyntax();
})();
