/* Shared, dependency-free playground state. Browser storage never touches Codex files. */
(function (root) {
  'use strict';
  const copy = value => JSON.parse(JSON.stringify(value));
  const roles = ['question', 'reply', 'tools', 'intermediate', 'answer'];
  const roleLabels = {question:'Question',reply:'Reply',tools:'Tools',intermediate:'Intermediate answer',answer:'Final answer'};
  const sharedCardKeys = ['expandable','default_expanded','max_width','padding_x','padding_y','background','title_visible','title'];
  function applyCardValue(settings,targets,key,value){
    if(!sharedCardKeys.includes(key)||!targets.length||targets.some(role=>!roles.includes(role)))throw new Error('Choose cards and a shared style setting.');
    const next=copy(settings);
    for(const role of new Set(targets))card(next,role)[key]=copy(value);
    if(!validSettings(next))throw new Error('Invalid card setting.');
    return next;
  }
  function targetLabel(targets,source){
    return targets.length===1&&targets[0]===source?'Current card':roles.every(role=>targets.includes(role))?'All cards':`${targets.length} selected cards`;
  }
  // Matches mycodx_style::COLORS. Stored values use the native schema.
  const colors = [['None','none'],['Auto','auto'],['Gray',{rgb:[55,58,64]}],['Slate',{rgb:[49,65,82]}],
    ['Blue',{rgb:[35,63,105]}],['Teal',{rgb:[29,77,78]}],['Green',{rgb:[45,76,49]}],
    ['Amber',{rgb:[100,74,31]}],['Rose',{rgb:[99,48,65]}],['Purple',{rgb:[72,51,96]}]];
  const card = (settings, role) => role === 'reply' || role === 'intermediate'
    ? settings[role] : settings.cards[{question: 0, tools: 1, answer: 2}[role]];
  const cardMode = settings => settings.show_tools ? (settings.show_intermediate?'2: All cards':'Custom')
    : (settings.show_intermediate?'0: Progress':'1: Answers only');
  function nextCardMode(settings) {
    const mode=cardMode(settings);
    return {...settings,show_tools:mode==='1: Answers only',show_intermediate:mode!=='0: Progress'};
  }
  function applyPalette(settings, palette) {
    const next = copy(settings);
    roles.forEach((role, index) => Object.assign(card(next, role), copy(palette.colors[index])));
    return next;
  }
  function validSettings(settings) {
    if (!settings || !Array.isArray(settings.cards) || settings.cards.length !== 3) return false;
    const color = value => ['none','auto'].includes(value)
      || (value && Array.isArray(value.rgb) && value.rgb.length === 3 && value.rgb.every(n => Number.isInteger(n) && n >= 0 && n <= 255));
    return typeof settings.show_tools === 'boolean' && typeof settings.show_intermediate === 'boolean' && roles.every(role => {
      const c = card(settings, role);
      return c && [50,60,70,80,100].includes(c.max_width) && Number.isInteger(c.padding_x) && c.padding_x >= 0 && c.padding_x <= 6
        && Number.isInteger(c.padding_y) && c.padding_y >= 0 && c.padding_y <= 6 && typeof c.title === 'string' && c.title.length <= 100
        && typeof c.title_visible === 'boolean' && typeof c.expandable === 'boolean' && typeof c.default_expanded === 'boolean'
        && color(c.background);
    });
  }
  // Keep focus behavior identical to native CardStyle::colors_for.
  const brighten = rgb => rgb.map(v => v + Math.ceil((255-v)*.12));
  function surface(value, outer, active = false) {
    const base = value?.rgb || (value === 'auto'
      ? outer.map(v => outer.reduce((a,b)=>a+b,0)>382 ? Math.max(0,v-18) : Math.min(255,v+24)) : outer);
    return active ? brighten(base) : base;
  }
  function migrate(settings) {
    const next = copy(settings);
    roles.forEach(role => delete card(next,role).background_active);
    return next;
  }
  // Initialize once when history is opened; later live cards keep their own defaults.
  function restoredAnswers(items) {
    return new Map(items.filter(item=>['answer','intermediate'].includes(item.role))
      .map(item=>[item.id,item.role==='answer']));
  }
  const luminance = rgb => rgb.map(v=>{v/=255;return v<=.04045?v/12.92:((v+.055)/1.055)**2.4;})
    .reduce((sum,v,i)=>sum+v*[.2126,.7152,.0722][i],0);
  const contrast = (a,b) => (Math.max(luminance(a),luminance(b))+.05)/(Math.min(luminance(a),luminance(b))+.05);
  function foreground(bg) {
    const fg=bg[0]*299+bg[1]*587+bg[2]*114>140000?[20,20,20]:[240,240,240];
    return contrast(fg,bg)>=4.5?fg:(contrast([0,0,0],bg)>contrast([255,255,255],bg)?[0,0,0]:[255,255,255]);
  }
  function groups(items,settings,revealId=null){
    const result=[];
    for(const item of items){
      if(item.id!==revealId&&((item.role==='tools'&&!settings.show_tools)||(item.role==='intermediate'&&!settings.show_intermediate)))continue;
      const previous=result.at(-1);
      if(previous&&previous.role===item.role&&['tools','intermediate'].includes(item.role)){
        previous.text+='\n\n'+item.text;previous.members.push(item.id);previous.actions+=(item.actions||0);previous.failed||=item.failed;
      }else result.push({...item,members:[item.id]});
    }
    return result;
  }
  const filters=['all','questions','tools','intermediate','answer'];
  const filterLabels={all:'All',questions:'Questions/replies',tools:'Tools',intermediate:'Intermediate',answer:'Final answers'};
  // Deadline-based, so throttled background tabs never extend the preview.
  function workingPreview(now=()=>performance.now()){
    let deadline=null;
    return {start(){if(this.remaining())return false;deadline=now()+7000;return true;},
      remaining(){return deadline===null?0:Math.max(0,Math.ceil((deadline-now())/1000));},
      state(){return deadline===null?'idle':this.remaining()?'working':'worked';},
      stop(){deadline=null;}};
  }
  // Port of mycodx_status::surface, summary_shimmer, and motion's truecolor bullet.
  function statusFrame(settings,outer,terminalFg,elapsed,{animated=true,completed=false}={}){
    const mix=(fg,bg,t)=>{const a=Math.fround(t),b=Math.fround(1-a);return fg.map((v,i)=>Math.floor(Math.fround(Math.fround(v*a)+Math.fround(bg[i]*b))));};
    let base=surface(card(settings,completed?'answer':'intermediate').background,outer);
    const fg=foreground(base),extreme=contrast(fg,[255,255,255])>contrast(fg,[0,0,0])?[255,255,255]:[0,0,0];
    for(let i=0;i<32&&contrast(fg,mix(fg,base,.18))<4.5;i++)base=mix(extreme,base,.1);
    const seconds=Math.max(0,elapsed)/1000,period=Math.max(1,['one_second','two_seconds','three_seconds','four_seconds'].indexOf(settings.working_animation)+1);
    const phase=animated&&!completed?Math.fround((1-Math.cos(2*Math.PI*(seconds%period)/period))/2):0;
    const background=mix(fg,base,Math.fround(Math.fround(.06)+Math.fround(Math.fround(.12)*phase))),halfWidth=3,width=7;
    const sweep=Math.min(Math.max(0,seconds-.6)%4,1),position=sweep*(width+2*halfWidth)-halfWidth;
    const letters=Array.from('Working',(_,i)=>{
      if(!animated||completed)return fg;
      const distance=Math.min(Math.abs(i+.5-position)/halfWidth,1),intensity=.5*(1+Math.cos(Math.PI*distance));
      return mix(terminalFg,outer,.5+.5*intensity);
    });
    const bulletDistance=Math.abs(10-Math.floor((seconds%2)/2*21));
    const bulletIntensity=bulletDistance<=5?.5*(1+Math.cos(Math.PI*bulletDistance/5)):0;
    return {background,foreground:fg,letters,bullet:animated&&!completed?mix(outer,terminalFg,bulletIntensity*.9):fg};
  }
  function composerAction(event,value){
    if(event.isComposing||event.keyCode===229||event.altKey||event.ctrlKey||event.metaKey)return null;
    if(event.key==='?'&&!value)return event.repeat?'ignore':'help';
    if(event.key!=='Enter'||event.shiftKey)return null;
    return event.repeat||!value.trim()?'ignore':value.trim()==='/custom'?'custom':'preview';
  }
  function commandSuggestion(value,start=value.length,end=start){
    return start===end&&end===value.length&&/^\/[a-z]*$/i.test(value)&&'/custom'.startsWith(value.toLowerCase())?'/custom':null;
  }
  function commandSuggestionAction(event){
    if(event.isComposing||event.keyCode===229||event.altKey||event.ctrlKey||event.metaKey||event.shiftKey)return null;
    if(event.key==='Escape')return 'dismiss';
    if(event.key==='ArrowUp'||event.key==='ArrowDown')return 'select';
    if(event.key==='Tab'||event.key==='Enter')return event.repeat?'ignore':event.key==='Tab'?'complete':'submit';
    return null;
  }
  function footer({columns=120,browsing=false,navigationFilter='all',navigationEmpty=false,searchMode='closed',query='',matches=0,filter='all',hasDraft=false,working=false,help=false,scrolled=false,mode='0: Progress'}={}){
    const fit=lines=>lines.find(line=>Array.from(line).length<=columns)||lines.at(-1);
    if(help)return '? or esc close';
    if(searchMode==='editing'){
      const status=!query.trim()?'Type to find':matches?'enter accept · ctrl+p older · ctrl+n newer':'No matches';
      return fit([`${status} · ${filterLabels[filter]} · tab filter · esc cancel`,`${status} · tab filter · esc cancel`,`${matches?'enter accept':status} · esc cancel`,'esc cancel']);
    }
    if(searchMode==='reading')return fit([`Find${filter==='all'?'':` [${filterLabels[filter]}]`} · ctrl+p older · ctrl+n newer · esc latest`,'ctrl+p older · ctrl+n newer · esc latest','esc latest']);
    if(browsing){const label=filterLabels[navigationFilter],empty=navigationEmpty?' (no visible cards)':'';return fit([
      `Browsing [${label}]${empty} · tab filter · ↑↓ scroll · ctrl+up/down cards · enter fold · shift+f4 ${mode} · esc back`,
      `Browsing [${label}]${empty} · tab filter · ctrl+up/down cards · enter fold · esc back`,
      `[${label}]${empty} · tab filter · ctrl+up/down cards · enter fold`,
      `[${label}]${empty} · tab filter · esc back`,`[${label}] · tab filter`,'tab filter · esc back']);}
    if(scrolled)return fit(['Back to bottom · ctrl+end latest','ctrl+end latest']);
    if(working)return 'ctrl+c stop preview';
    return hasDraft?'':'? for shortcuts';
  }
  function excerpt(items,maxItems=40,maxChars=32000){
    const chosen=[];let characters=0,shortened=0;
    for(let index=items.length-1;index>=0;index--){
      if(chosen.length>=maxItems||maxChars-characters<64)break;
      const item=items[index],limit=Math.min(item.role==='tools'?2000:8000,maxChars-characters);
      const suffix='\n[Text shortened for preview]';
      const text=item.text.length>limit?item.text.slice(0,Math.max(0,limit-suffix.length))+suffix:item.text;
      shortened+=text!==item.text;characters+=text.length;chosen.push({...item,text});
    }
    return {items:chosen.reverse(),characters,shortened,discarded:items.length-chosen.length};
  }
  function search(items,query,filter='all'){
    const value=query.trim().toLocaleLowerCase();if(!value)return [];
    return items.filter(item=>roles.includes(item.role)&&(filter==='all'||(filter==='questions'?['question','reply'].includes(item.role):item.role===filter))&&item.text.toLocaleLowerCase().includes(value)).map(i=>i.id);
  }
  const matchesFilter = (item,filter='all') => !!item&&roles.includes(item.role)&&(filter==='all'||(filter==='questions'?['question','reply'].includes(item.role):item.role===filter));
  const nextFilter = (filter,backwards=false) => filters[(filters.indexOf(filter)+(backwards?filters.length-1:1))%filters.length];
  function nearestCard(items,id,filter='all'){
    const anchor=items.findIndex(i=>i.id===id),origin=anchor<0?items.length-1:anchor;
    return items.map((item,index)=>({item,index})).filter(({item})=>matchesFilter(item,filter))
      .sort((a,b)=>Math.abs(a.index-origin)-Math.abs(b.index-origin)||a.index-b.index)[0]?.item.id||null;
  }
  function navigate(items,id,direction,filter='all'){
    if(!['up','down'].includes(direction))return id;
    const index=items.findIndex(i=>i.id===id);
    if(index<0)return nearestCard(items,id,filter);
    const candidates=direction==='up'?items.slice(0,index).reverse():items.slice(index+1);
    return candidates.find(i=>matchesFilter(i,filter))?.id||(matchesFilter(items[index],filter)?id:null);
  }
  function keyAction(event,{browsing=false,searchOpen=false,searchReading=false,matches=0,searchInput=false,editable=false,card=false,button=false,selection=false}={}){
    const {key,ctrlKey,altKey,metaKey,shiftKey}=event;
    if(event.isComposing||altKey||metaKey)return null;
    if(key==='F4'&&shiftKey)return ctrlKey||searchOpen||searchReading||selection||event.repeat?null:'card-mode';
    if(key==='Escape')return 'escape';
    if((searchOpen||searchReading)&&ctrlKey&&['p','n'].includes(key.toLowerCase()))return key.toLowerCase()==='p'?'previous-match':'next-match';
    if(key==='F3')return searchOpen&&matches?(shiftKey?'previous-match':'next-match'):'search';
    if(searchOpen&&searchInput){
      if(key==='Tab')return shiftKey?'previous-filter':'next-filter';
      if(key==='Enter')return 'accept-search';
      if(key!=='F4'&&!(ctrlKey&&key==='End'))return null;
    }
    if(key==='F4')return ctrlKey?null:'browse';
    if(ctrlKey&&key==='End')return 'bottom';
    if(editable)return null;
    if(browsing&&!searchOpen&&!searchReading&&!selection&&key==='Tab'&&!ctrlKey)return event.repeat?'ignore':shiftKey?'previous-card-filter':'next-card-filter';
    if(browsing&&ctrlKey&&['ArrowUp','ArrowDown'].includes(key))return 'card-'+key.slice(5).toLowerCase();
    if(browsing&&ctrlKey&&['ArrowLeft','ArrowRight'].includes(key))return 'ignore';
    if(ctrlKey)return null;
    if(browsing){
      if(['ArrowUp','ArrowDown','PageUp','PageDown','Home','End'].includes(key))return 'scroll-'+key;
    }
    if(key==='Enter'&&!button&&(browsing||card))return 'fold';
    return null;
  }
  root.PlaygroundModel = {copy, roles, roleLabels, sharedCardKeys, applyCardValue, targetLabel, colors, card, cardMode, nextCardMode, applyPalette, validSettings, brighten, surface, migrate, restoredAnswers, foreground, contrast, groups, excerpt, search, filters, filterLabels, matchesFilter, nextFilter, nearestCard, navigate, keyAction, workingPreview, statusFrame, composerAction, commandSuggestion, commandSuggestionAction, footer};
  if (typeof module !== 'undefined') module.exports = root.PlaygroundModel;
})(globalThis);
