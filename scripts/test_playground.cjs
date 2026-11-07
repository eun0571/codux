'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const M = require('../playground/model.js');
const root = path.resolve(__dirname, '../playground');
const context = vm.createContext({window:{}});
vm.runInContext(fs.readFileSync(path.join(root,'palettes.js'),'utf8'),context);
const defaults = M.copy(context.window.PLAYGROUND_DEFAULTS), palettes = M.copy(context.window.PLAYGROUND_PALETTES);
assert(palettes.length>=38);
assert(M.validSettings(defaults));
assert.equal(M.card(defaults,'answer').background,'none');
const ocean=palettes.find(p=>p.id==='base16-ocean-dark').choices[0];
for(const role of ['question','reply','tools','intermediate'])
  assert.deepEqual(M.card(defaults,role).background,ocean.colors[M.roles.indexOf(role)].background);
for(const role of M.roles) {
  assert.equal(M.card(defaults,role).padding_x,1);
  assert.equal(M.card(defaults,role).padding_y,1);
}
for(const palette of palettes) {
  assert(palette.choices.length>=18);
  assert(palette.choices[0].name.includes('(recommended)'));
  for(const choice of palette.choices) {
    const next=M.applyPalette(defaults,choice);
    assert(M.validSettings(next));
    const removeColors=s=>M.roles.map(r=>{const {background,...rest}=M.card(s,r);return rest;});
    assert.deepEqual(removeColors(next),removeColors(defaults));
    assert.equal(next.show_tools,defaults.show_tools);
  }
}
assert(!M.validSettings({...defaults,cards:[]}));
// A bulk edit must change only its element and targets, without mutating the baseline.
const beforeBulk=M.copy(defaults), selectedCards=['question','reply','answer'];
const bulk=M.applyCardValue(defaults,selectedCards,'padding_x',4);
for(const role of M.roles){
  const expected=M.copy(M.card(defaults,role));if(selectedCards.includes(role))expected.padding_x=4;
  assert.deepEqual(M.card(bulk,role),expected);
}
assert.deepEqual(defaults,beforeBulk);assert.equal(bulk.show_tools,defaults.show_tools);
const commonBackground=M.applyCardValue(defaults,M.roles,'background',{rgb:[12,34,56]});
for(const role of M.roles)assert.deepEqual(M.card(commonBackground,role).background,{rgb:[12,34,56]});
M.card(commonBackground,'question').background.rgb[0]=99;
assert.equal(M.card(commonBackground,'reply').background.rgb[0],12,'Each target owns its value');
assert.throws(()=>M.applyCardValue(defaults,[],'padding_x',1));
assert.throws(()=>M.applyCardValue(defaults,['notice'],'padding_x',1));
assert.throws(()=>M.applyCardValue(defaults,M.roles,'align','right'));
assert.equal(M.targetLabel(['question'],'question'),'Current card');assert.equal(M.targetLabel(M.roles,'question'),'All cards');
assert.equal(M.targetLabel(['reply','answer'],'question'),'2 selected cards');
// Exercise settings navigation with a minimal DOM; rendering is verified separately.
{
  class Element {
    constructor(){this.children=[];this.listeners={};this.style={setProperty(){}};this.offsetTop=0;this.offsetHeight=20;this.clientHeight=500;this.scrollTop=0;this.hidden=true;}
    append(...children){this.children.push(...children);}
    prepend(child){this.children.unshift(child);}
    replaceChildren(...children){this.children=children;}
    setAttribute(){}
    addEventListener(type,fn){this.listeners[type]=fn;}
    focus(){}
    querySelectorAll(){return this.children.filter(child=>child.className==='menu-item');}
  }
  const elements=new Map(),lookup=selector=>{
    if(selector==='#menu-content .apply-scope')return lookup('#menu-content').children.find(child=>child.className==='apply-scope');
    if(!elements.has(selector))elements.set(selector,new Element());return elements.get(selector);
  };
  let saved;
  const sandbox=vm.createContext({PlaygroundModel:M,PLAYGROUND_DEFAULTS:M.copy(defaults),PLAYGROUND_PALETTES:palettes,
    PLAYGROUND_RELEASE:{version:'test',upstream:'test'},performance:{now:()=>0},window:{},document:{querySelector:lookup,createElement:()=>new Element(),addEventListener(){}},
    localStorage:{getItem(){return null;},setItem(key,value){saved=JSON.parse(value);}},
    createSessionViewer:()=>({render(){},setOuter(){},isWorking(){return false;}})});
  const source=fs.readFileSync(path.join(root,'app.js'),'utf8').replace('  setSyntax();',
    '  globalThis.editor={openCustom,open,back,chooseEntry,get settings(){return settings;},get entries(){return entries;},get page(){return current();}}; setSyntax();');
  vm.runInContext(source,sandbox);
  const editor=sandbox.editor,choose=label=>{
    const index=editor.entries.findIndex(entry=>entry.label===label);assert(index>=0,label);
    editor.chooseEntry(index,false);editor.entries[index].action();
  };
  editor.openCustom();choose('Question');choose('Prompt style');choose('Padding');choose('Horizontal');
  lookup('#menu-content .apply-scope').listeners.click();choose('All cards');
  editor.chooseEntry(4,false);
  for(const role of M.roles)assert.equal(M.card(editor.settings,role).padding_x,4);
  assert.equal(saved,undefined,'Preview never saves preferences');
  editor.back();assert.deepEqual(M.copy(editor.settings),defaults,'Esc restores every affected card');
  choose('Horizontal');lookup('#menu-content .apply-scope').listeners.click();choose('Current card');
  lookup('#menu-content .apply-scope').listeners.click();choose('Selected cards…');
  choose('☐ Final answer');choose('Use selected cards');choose('3 columns');
  assert.deepEqual(Array.from(editor.page.targets),['question','answer'],'The active style branch retains its targets');
  for(const role of M.roles)assert.equal(M.card(saved.settings,role).padding_x,['question','answer'].includes(role)?3:1);
  // Changing targets on the parent after a committed child edit must not resurrect old values.
  lookup('#menu-content .apply-scope').listeners.click();choose('All cards');choose('Vertical');choose('1 row');
  for(const role of M.roles){assert.equal(M.card(saved.settings,role).padding_y,2);assert.equal(M.card(saved.settings,role).padding_x,['question','answer'].includes(role)?3:1);}
  while(editor.page)editor.back();editor.openCustom();choose('Tools');choose('Background');
  assert.deepEqual(Array.from(editor.page.targets),['tools'],'Reopening an editor targets only its own card');
  lookup('#menu-content .apply-scope').listeners.click();choose('Selected cards…');choose('☑ Tools');
  assert.equal(editor.entries[0].disabled,true,'Empty target selection cannot be applied');
  editor.back();editor.back();assert.deepEqual(Array.from(editor.page.targets),['tools'],'Esc discards target selection changes');
}
const html=fs.readFileSync(path.join(root,'index.html'),'utf8');
assert(html.indexOf('id="search-panel"')>html.indexOf('id="command"'),'Search belongs below the composer');
assert(html.indexOf('id="search-panel"')<html.indexOf('class="terminal-footer"'));
assert(html.indexOf('id="conversation-cards"')<html.indexOf('id="working-preview"')&&html.indexOf('id="working-preview"')<html.indexOf('id="bottom-button"'),
  'Working belongs in the scrollable conversation, after the cards, rather than over the answer or composer');
for(const removed of ['library-button','guide-toggle','custom-button','browse-button','search-button','display-button','session-title','session-info','preview-focus','storage-label'])
  assert(!html.includes(`id="${removed}"`),`Removed external control: ${removed}`);
for(const asset of ['app.js','viewer.js']){
  const source=fs.readFileSync(path.join(root,asset),'utf8');
  for(const [,id]of source.matchAll(/\$\('#([\w-]+)'\)/g))assert(html.includes(`id="${id}"`),`Missing element ${id} in ${asset}`);
}
assert(!html.includes('preview-stage')&&!html.includes('browser-status'),'The terminal directly fills the main workspace');
const viewer=fs.readFileSync(path.join(root,'viewer.js'),'utf8');
assert(!viewer.includes("el('small','code-language'"),'Native code has no separate language heading');
for(const [,asset] of html.matchAll(/(?:src|href)="([^"#]+\.(?:js|css))"/g)){
  if(asset!=='release.js')assert(fs.existsSync(path.join(root,asset)),asset); // Generated by the static builder.
}
for(const asset of ['app.js','model.js','sessions.js','viewer.js','palettes.js'])new vm.Script(fs.readFileSync(path.join(root,asset),'utf8'));

// Old independent focus colors do not affect the derived surface or survive migration.
for (const outer of [[20,20,20],[240,240,240]]) {
  for (const bg of ['none','auto',{rgb:[30,60,90]}]) {
    const resting=M.surface(bg,outer), focused=M.surface(bg,outer,true);
    assert(focused.every((v,i)=>v>resting[i]));
    assert.deepEqual(focused,M.brighten(resting));
  }
}
assert.deepEqual(M.brighten([254,255,0]),[255,255,31]);
const legacy=M.copy(defaults);
M.roles.forEach(role=>M.card(legacy,role).background_active={rgb:[255,0,0]});
assert.deepEqual(M.migrate(legacy),defaults);
const restored = M.restoredAnswers([
  {id:'q1',role:'question'}, {id:'p1',role:'intermediate'}, {id:'a1',role:'answer'},
  {id:'q2',role:'question'}, {id:'p2',role:'intermediate'}, {id:'a2',role:'answer'}, {id:'t',role:'tools'},
]);
assert.deepEqual([...restored],[['p1',false],['a1',true],['p2',false],['a2',true]]);
assert.equal(restored.has('new-answer'),false);
assert.deepEqual([...M.restoredAnswers([{id:'p',role:'intermediate'}])],[['p',false]]);
for(let value=0;value<=255;value++){
  const bg=[value,value,value];
  assert(M.contrast(M.foreground(bg),bg)>=4.5,`Unreadable card at ${value}`);
}
const S=require('../playground/sessions.js');
const row=(type,payload)=>JSON.stringify({timestamp:'2026-11-06T00:00:00Z',type,payload});
const event=payload=>row('event_msg',payload),response=payload=>row('response_item',payload);
const completed=(type,id,content,phase)=>event({type:'item_completed',item:{type,id,content:[{type:'text',text:content}],phase}});
const parsed=S.parse([
  row('session_meta',{id:'local-only',cwd:'C:/project',cli_version:'0.166.0'}),
  event({type:'task_started',turn_id:'one'}),
  response({type:'message',role:'developer',content:[{text:'INSTRUCTIONS DO NOT DISPLAY'}]}),
  response({type:'message',role:'user',content:[{text:'Repeated question'}]}),
  completed('UserMessage','u1','Repeated question'),
  completed('AgentMessage','i1','Checking first','commentary'),
  response({type:'message',role:'assistant',phase:'commentary',content:[{text:'Checking first'}]}),
  response({type:'custom_tool_call',call_id:'wrapper',name:'exec',input:'nested commands'}),
  event({type:'item_completed',item:{type:'CommandExecution',id:'c1',command:'rg token',aggregated_output:'hidden needle',exit_code:0}}),
  response({type:'custom_tool_call_output',call_id:'wrapper',output:'duplicate wrapper'}),
  completed('AgentMessage','a1','Final <img src="https://example.com/secret">','final_answer'),
  event({type:'task_complete',last_agent_message:'Final <img src="https://example.com/secret">'}),
  event({type:'task_started',turn_id:'two'}),
  completed('UserMessage','u2','Repeated question'),
  completed('AgentMessage','a2','Another final','final_answer'),
  '{truncated',
].join('\n'));
assert.deepEqual(parsed.items.map(i=>i.role),['question','intermediate','tools','answer','question','answer']);
assert.equal(parsed.items.filter(i=>i.text==='Repeated question').length,2);
assert.equal(parsed.stats.malformed,1);
assert(!parsed.items.some(i=>i.text.includes('INSTRUCTIONS')||i.text.includes('wrapper')));
assert(parsed.items.some(i=>i.text.includes('<img')),'Source text must remain literal, not evaluated');
const legacySession=S.parse([
  event({type:'task_started',turn_id:'legacy'}),event({type:'user_message',message:'Start'}),
  response({type:'message',role:'user',content:[{text:'Start'}]}),
  event({type:'agent_message',message:'Question?',phase:'commentary',questions:[{question:'Which?'}]}),
  event({type:'user_message',message:'<send_user_message_question_reply>[{"questionItemId":"ask","question":"Which?","answer":"Answer to question"}]</send_user_message_question_reply>'}),
  event({type:'agent_message',message:'First candidate'}),event({type:'agent_message',message:'Last candidate'}),
].join('\n'));
assert.deepEqual(legacySession.items.map(i=>i.role),['question','intermediate','reply','intermediate','answer']);
const replyEnvelope='<send_user_message_question_reply>[{"questionItemId":"ask","question":"Q?","answer":"A"}]</send_user_message_question_reply>';
assert.equal(S.formReply(replyEnvelope),'> Q?\n\nA');
assert.equal(S.formReply('Example: '+replyEnvelope),null,'Quoted reply syntax is still an ordinary prompt');
assert.equal(S.formReply('<send_user_message_question_reply>[]</send_user_message_question_reply>'),null);
assert.equal(S.formReply('# Context from my IDE setup:\nFiles\n## My request for Codex:\n'+replyEnvelope),'> Q?\n\nA');
const fallback=S.parse([
  response({type:'message',role:'user',content:[{text:'Only response items'}]}),
  response({type:'function_call',call_id:'call',name:'read',arguments:'a.txt'}),
  response({type:'function_call_output',call_id:'call',output:'file content'}),
  response({type:'message',role:'assistant',content:[{text:'<proposed_plan>My plan</proposed_plan>'}],phase:'final_answer'}),
  event({type:'task_complete',last_agent_message:'<proposed_plan>My plan</proposed_plan>'}),
].join('\n'));
assert.deepEqual(fallback.items.map(i=>i.role),['question','tools','answer']);
assert(fallback.items[1].text.includes('file content'));assert.equal(fallback.items[2].text,'My plan');
const questions=S.parse([
  completed('UserMessage','u','Start'),
  event({type:'item_completed',item:{type:'AgentMessage',id:'ask',content:[],questions:[{title:'Which direction?'}]}}),
  completed('UserMessage','reply','<send_user_message_question_reply>[{"questionItemId":"ask","question":"Which direction?","answer":"Left"}]</send_user_message_question_reply>'),
  event({type:'item_completed',item:{type:'Plan',id:'plan',text:'The chosen plan'}}),
  event({type:'task_complete',last_agent_message:'The chosen plan'}),
].join('\n'));
assert.deepEqual(questions.items.map(i=>i.role),['question','intermediate','reply','answer']);
assert.equal(questions.items[1].text,'Which direction?');
// A bounded excerpt can start mid-turn, before either copy exposes a turn ID.
const canonical=(type,id,body,phase,turn='partial')=>event({type:'item_completed',turn_id:turn,item:{type,id,content:[{text:body}],phase}});
const partial=S.parse([
  response({type:'message',id:'q-part',role:'user',content:[{text:'Prompt'}]}),
  canonical('UserMessage','q-part','Prompt'),
  canonical('AgentMessage','i-part','Checking','commentary'),
  response({type:'message',id:'i-part',role:'assistant',content:[{text:'Checking'}],phase:'commentary'}),
  row('turn_context',{}), // Same-turn context refresh must not split the group.
  canonical('AgentMessage','a-part','Done','final_answer'),
  response({type:'message',id:'a-part',role:'assistant',content:[{text:'Done'}],phase:'final_answer'}),
  event({type:'task_complete',turn_id:'partial',last_agent_message:'Done\n[Text shortened for preview]'}),
].join('\n'));
assert.deepEqual(partial.items.map(i=>[i.role,i.text]),[['question','Prompt'],['intermediate','Checking'],['answer','Done']]);
assert(partial.items.every(i=>i.turn==='partial'));
const noInferredReply=S.parse([
  canonical('AgentMessage','ask','Which direction?','commentary'),
  canonical('UserMessage','normal','A new prompt'),
  canonical('AgentMessage','final','Done','final_answer'),
].join('\n'));
assert.equal(noInferredReply.items[1].role,'question','An ordinary prompt is not a question-form reply');
const identicalPrompts=S.parse([
  canonical('UserMessage','repeat1','Repeat','', 'one'),canonical('AgentMessage','answer1','Done','final_answer','one'),
  event({type:'task_started',turn_id:'two'}),canonical('UserMessage','repeat2','Repeat','','two'),canonical('AgentMessage','answer2','Done','final_answer','two'),
].join('\n'));
assert.deepEqual(identicalPrompts.items.map(i=>i.role),['question','answer','question','answer'],'Repeated text across turns is genuine history');
const sample=[{id:'q',role:'question',text:'question',turn:'1'},
  {id:'i',role:'intermediate',text:'first',turn:'1'}, {id:'t',role:'tools',text:'secret needle',actions:2,turn:'1'},
  {id:'i2',role:'intermediate',text:'second',turn:'1'}, {id:'n',role:'notice',text:'compacted',turn:'1'},
  {id:'i3',role:'intermediate',text:'third',turn:'1'}, {id:'a',role:'answer',text:'final',turn:'1'}];
const grouped=M.groups(sample,defaults);
assert.deepEqual(grouped.find(i=>i.id==='i').members,['i','i2']);
assert.equal(M.groups([{id:'i1',role:'intermediate',turn:'root',text:'First'},{id:'i2',role:'intermediate',turn:'continued',text:'Second'}],defaults).length,1,'A server turn boundary alone does not split native intermediate cards');
assert.equal(grouped.find(i=>i.id==='i3').text,'third');
assert.deepEqual(M.search(sample,'NEEDLE','tools'),['t']);
assert.deepEqual(M.search(sample,'NEEDLE','answer'),[]);
assert(M.groups(sample,defaults,'t').some(i=>i.id==='t'));
assert(!M.groups(sample,defaults).some(i=>i.id==='t'));
assert.equal(M.navigate(grouped,'a','right'),'q');assert.equal(M.navigate(grouped,'q','left'),'i');
assert.equal(M.navigate(grouped,'i','down'),'i3');assert.equal(M.navigate(grouped,'q','up'),'q');
assert.equal(M.navigate([],null,'down'),null);
// Visibility modes leave questions, notices, final answers and styles intact.
const originalModeSettings=M.copy(defaults);
originalModeSettings.cards[0].padding_x=4;
let modeSettings=originalModeSettings;
for(const [label,tools,intermediate]of[
  ['1: Answers only',false,false],['2: All cards',true,true],['0: Progress',false,true]]){
  modeSettings=M.nextCardMode(modeSettings);
  assert.equal(M.cardMode(modeSettings),label);
  const cards=M.groups(sample,modeSettings);
  assert.equal(cards.some(i=>i.role==='tools'),tools);
  assert.equal(cards.some(i=>i.role==='intermediate'),intermediate);
  for(const role of ['question','notice','answer'])assert(cards.some(i=>i.role===role));
  assert.deepEqual(modeSettings.cards,originalModeSettings.cards);
}
assert.deepEqual(modeSettings,originalModeSettings);
assert.equal(M.cardMode(M.nextCardMode({...defaults,show_tools:true,show_intermediate:false})),'0: Progress');
// Exercise keyboard conflicts as well as ordinary browsing/search actions.
const key=(key,state={},modifiers={})=>M.keyAction({key,...modifiers},state);
assert.equal(key('ArrowDown',{browsing:true}),'scroll-ArrowDown');
assert.equal(key('ArrowDown',{browsing:true},{ctrlKey:true}),'card-down');
assert.equal(key('ArrowDown',{browsing:true,editable:true}),null);
assert.equal(key('Enter',{browsing:true}),'fold');
assert.equal(key('Enter',{browsing:true,button:true}),null,'A focused Copy button must not fold its card');
assert.equal(key('Enter',{editable:true}),null,'Multiline drafts must not send or fold');
assert.equal(key('t',{browsing:true}),null);assert.equal(key('t',{browsing:true,editable:true}),null);
assert.equal(key('e',{browsing:true}),null,'Do not imitate native rewind with a different action');assert.equal(key('e'),null);
assert.equal(key('t',{browsing:true},{ctrlKey:true}),null,'Do not pretend to replace browser tab shortcuts');
assert.equal(key('F4',{browsing:true},{altKey:true}),null,'Do not intercept window close');
assert.equal(key('F4',{}, {shiftKey:true}),'card-mode');
assert.equal(key('F4',{editable:true},{shiftKey:true}),'card-mode','Keep the draft while changing display');
assert.equal(key('F2'),null,'Plain F2 is not the display shortcut');
assert.equal(key('F6'),null,'Leave the browser focus shortcut alone');
assert.equal(key('F4',{}, {shiftKey:true,repeat:true}),null);
for(const state of [{searchOpen:true},{selection:true}])assert.equal(key('F4',state,{shiftKey:true}),null);
for(const modifiers of [{shiftKey:true,ctrlKey:true},{shiftKey:true,altKey:true},{shiftKey:true,metaKey:true},{shiftKey:true,isComposing:true}])
  assert.equal(key('F4',{},modifiers),null);
assert.equal(key('F4',{editable:true}),'browse');assert.equal(key('F4',{},{isComposing:true}),null);
assert.equal(key('F3',{editable:true}),'search');assert.equal(key('F3',{searchOpen:true,matches:2},{shiftKey:true}),'previous-match');
assert.equal(key('Tab',{searchOpen:true,searchInput:true,editable:true}),'next-filter');
assert.equal(key('Enter',{searchOpen:true,searchInput:true,editable:true}),'accept-search');
for(const state of [{searchOpen:true,searchInput:true,editable:true},{searchReading:true}]){
  assert.equal(key('p',state,{ctrlKey:true}),'previous-match');
  assert.equal(key('n',state,{ctrlKey:true}),'next-match');
}
assert.equal(key('p',{}, {ctrlKey:true}),null,'Browser print is untouched outside transcript search');
assert.equal(key('F4',{searchReading:true},{shiftKey:true}),null);
assert.equal(key('End',{editable:true},{ctrlKey:true}),'bottom');
// A preview is local, deadline based, and never extended by repeated submits.
let clock=1000;const preview=M.workingPreview(()=>clock);
assert.equal(preview.state(),'idle');
assert.equal(preview.remaining(),0);assert.equal(preview.start(),true);assert.equal(preview.remaining(),7);
assert.equal(preview.state(),'working');
clock+=2000;assert.equal(preview.remaining(),5);assert.equal(preview.start(),false);
clock+=4999;assert.equal(preview.remaining(),1);clock++;assert.equal(preview.remaining(),0);
assert.equal(preview.state(),'worked');
assert.equal(preview.start(),true);clock+=60000;assert.equal(preview.remaining(),0,'Background-tab throttling cannot extend a preview');
preview.start();preview.stop();assert.equal(preview.remaining(),0);
assert.equal(preview.state(),'idle','Cancellation must not report Worked');
const statusSettings=M.applyCardValue(defaults,['intermediate'],'background',{rgb:[40,40,40]});
statusSettings.working_animation='two_seconds';
const frame=(ms,options={})=>M.statusFrame(statusSettings,[24,24,24],[230,230,230],ms,options);
assert.deepEqual(frame(0).background,[52,52,52]);assert.deepEqual(frame(1000).background,[76,76,76]);
assert.deepEqual(frame(2000).background,frame(0).background);
assert.deepEqual(frame(0).letters,frame(599).letters,'Header waits 600 ms before the first sweep');
assert(new Set(frame(1000).letters.map(c=>c.join(','))).size>1,'Shimmer moves across letters instead of fading the whole label');
assert.deepEqual(frame(1000).letters,frame(5000).letters,'Header sweep repeats independently every four seconds');
assert.deepEqual(frame(0,{animated:false}),frame(1000,{animated:false}));
assert.deepEqual(frame(0,{completed:true}).background,frame(2000,{completed:true}).background);
assert.deepEqual(frame(0,{completed:true}).background,M.statusFrame(defaults,[24,24,24],[230,230,230],0,{completed:true}).background,
  'Worked uses final-answer colors, independently of the progress fill');
const compose=(value,extra={})=>M.composerAction({key:'Enter',...extra},value);
assert.equal(compose('Hello'),'preview');assert.equal(compose(' /custom '),'custom');assert.equal(compose('  '),'ignore');
for(const modifiers of [{isComposing:true},{keyCode:229},{shiftKey:true},{ctrlKey:true},{altKey:true},{metaKey:true}])assert.equal(compose('Hello',modifiers),null);
assert.equal(compose('Hello',{repeat:true}),'ignore');
assert.equal(M.composerAction({key:'?'},''),'help');assert.equal(M.composerAction({key:'?'},'Question'),null);
// Completion only replaces a slash prefix at the end of an unselected, single-line draft.
for(const value of ['/','/c','/cu','/CUSTOM','/custom'])assert.equal(M.commandSuggestion(value),'/custom');
for(const value of ['', ' /cu','/theme','/search','/resume','/custom ','/custom help','/cu\n','Explain /custom','/customized'])assert.equal(M.commandSuggestion(value),null);
assert.equal(M.commandSuggestion('/custom',2,2),null);assert.equal(M.commandSuggestion('/custom',0,7),null);
const completion=(key,extra={})=>M.commandSuggestionAction({key,...extra});
assert.equal(completion('Tab'),'complete');assert.equal(completion('Enter'),'submit');assert.equal(completion('Escape'),'dismiss');
for(const key of ['ArrowUp','ArrowDown'])assert.equal(completion(key),'select');
for(const key of ['F3','F4','ArrowLeft','ArrowRight','a'])assert.equal(completion(key),null);
for(const modifiers of [{isComposing:true},{keyCode:229},{shiftKey:true},{ctrlKey:true},{altKey:true},{metaKey:true}])
  for(const key of ['Tab','Enter','Escape'])assert.equal(completion(key,modifiers),null);
assert.equal(completion('Tab',{repeat:true}),'ignore');assert.equal(completion('Enter',{repeat:true}),'ignore');
assert.equal(compose('/theme'),'preview','Unsupported commands still use the explicit Working simulation');
assert.equal(M.footer(),'? for shortcuts');assert.equal(M.footer({hasDraft:true}),'');
assert.equal(M.footer({working:true}),'ctrl+c stop preview');
assert.match(M.footer({searchMode:'editing'}),/Type to find.*tab filter.*esc cancel/);
assert.match(M.footer({searchMode:'editing',query:'x',matches:2}),/enter accept.*ctrl\+p older.*ctrl\+n newer/);
assert.match(M.footer({searchMode:'reading'}),/Find.*esc latest/);
assert.equal(M.footer({browsing:true,columns:32}),'Browsing · enter fold · esc back');
assert.match(M.footer({browsing:true,columns:120}),/ctrl\+arrows cards/);
assert.equal(M.footer({help:true}),'? or esc close');
const longItems=Array.from({length:200},(_,index)=>({id:String(index),role:index%2?'answer':'tools',text:'x'.repeat(10000),sourceOffset:index*20000}));
const small=M.excerpt(longItems);
assert(small.items.length<=40);assert(small.characters<=32000);assert(small.shortened>0);assert(small.discarded>0);
assert.equal(small.items.at(-1).id,'199');assert.equal(longItems[199].text.length,10000,'Preview clipping must not mutate parsed source');
const utf8=row('event_msg',{type:'user_message',message:'Caf\u00e9'}), afterUtf8=event({type:'agent_message',message:'Answer'});
assert.equal(S.parse(utf8+'\r\n'+afterUtf8,'utf8',1024,50).items[1].sourceOffset,50+Buffer.byteLength(utf8+'\r\n'));
assert.deepEqual(S.sessionLocation('Win32'),{path:'%USERPROFILE%\\.codex\\sessions',shortcut:'Ctrl+L'});
assert.deepEqual(S.sessionLocation('macOS'),{path:'~/.codex/sessions',shortcut:'Cmd+Shift+G'});
assert.deepEqual(S.sessionLocation('Linux'),{path:'~/.codex/sessions',shortcut:'Ctrl+L'});
console.log(`Playground: ${palettes.length} palettes, scoped card settings, rollout parsing, duplicate handling, grouping, search, navigation and keyboard routing passed.`);
