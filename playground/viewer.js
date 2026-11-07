/* Local session navigation. Session contents live only in this tab's memory. */
(function(root){
  'use strict';
  root.createSessionViewer=function({getSettings,changeSettings,say,openCustom,statusChanged=()=>{}}){
    const M=PlaygroundModel,$=s=>document.querySelector(s),host=$('#custom'),cardsHost=$('#conversation-cards');
    const empty=cardsHost.firstElementChild.cloneNode(true);
    const local=window.PLAYGROUND_LOCAL;
    let libraryGeneration=0,pickerGeneration=0,lastDirectory=null;
    if(local){
      $('.session-import').hidden=true;$('#session-location').hidden=true;$('#refresh-library').hidden=false;
      $('#session-filter').placeholder='Find a conversation or project';$('#session-filter').setAttribute('aria-label','Filter conversations');
      empty.querySelector('p').textContent='Finding sessions on this computer…';
    }
    let session={items:[]},files=[],selectedFile=null,loadGeneration=0,active=null,browsing=false,rendered=[],boxes=new Map();
    let matches=[],matchIndex=0,filter='all',query='',searchOpen=false,searchReading=false,helpOpen=false;
    const hasSearch=()=>searchOpen||searchReading;
    const preview=M.workingPreview();let previewTimer=null,lastRemaining=null;
    let dismissedCommand=null,composingCommand=false;
    let pageCursor=null,pageHistory=[],pageWindow=null,loadController=null;
    const manual=new Map(),restored=new Map();
    const labels={question:'Question',reply:'Reply',tools:'Tools',intermediate:'Intermediate answer',answer:'Final answer',notice:'Notice'};
    let outer=[24,24,24];
    function el(tag,cls,text){const n=document.createElement(tag);if(cls)n.className=cls;if(text!==undefined)n.textContent=text;return n;}
    function color(c){return `rgb(${c.join(',')})`;}
    function decorate(box,role,on){const style=M.card(getSettings(),role),bg=M.surface(style.background,outer,on);
      box.style.background=style.background==='none'&&!on?'transparent':color(bg);
      box.style.color=style.background==='none'&&!on?'var(--fg)':color(M.foreground(bg));
      box.classList.toggle('active-card',on);
    }
    function highlight(parent,value){
      if(!hasSearch()||!query.trim()){parent.append(document.createTextNode(value));return;}
      const needle=query.trim().toLocaleLowerCase(),lower=value.toLocaleLowerCase();let offset=0,index,count=0;
      while((index=lower.indexOf(needle,offset))!==-1&&count++<500){parent.append(document.createTextNode(value.slice(offset,index)),el('mark','',value.slice(index,index+needle.length)));offset=index+needle.length;}
      parent.append(document.createTextNode(value.slice(offset)));
    }
    function inline(parent,value){
      // Text-node rendering keeps arbitrary HTML and remote images inert.
      const pattern=/(`[^`\n]+`|\*\*[^*\n]+\*\*)/g;let previous=0;
      for(const match of value.matchAll(pattern)){
        highlight(parent,value.slice(previous,match.index));
        const code=match[0][0]==='`',n=el(code?'code':'strong');highlight(n,match[0].slice(code?1:2,code?-1:-2));parent.append(n);previous=match.index+match[0].length;
      }
      highlight(parent,value.slice(previous));
    }
    function markdown(parent,value){
      const lines=value.split('\n');let fenced=null,body=[];
      // Native Codux keeps fenced code in the answer's text flow, without a
      // separate language heading, framed surface or nested scroll container.
      const flushCode=()=>{const pre=el('pre','code-text');highlight(pre,body.join('\n'));parent.append(pre);body=[];};
      for(const line of lines){
        const fence=line.match(/^ {0,3}(`{3,}|~{3,})(.*)$/);
        if(fenced){if(fence&&fence[1][0]===fenced.char&&fence[1].length>=fenced.length&&!fence[2].trim()){flushCode();fenced=null;}else body.push(line);continue;}
        if(fence){fenced={char:fence[1][0],length:fence[1].length};continue;}
        const heading=line.match(/^(#{1,6})\s+(.*)$/),list=line.match(/^(\s*)([-*]|\d+[.)])\s+(.*)$/);
        const n=el(heading?'h'+Math.min(heading[1].length+1,6):'div',line.trim()?'markdown-line':'blank-line');
        if(heading)inline(n,heading[2]);else if(list){n.classList.add('list-line');inline(n,`${list[1]}${list[2]} ${list[3]}`);}else inline(n,line);
        parent.append(n);
      }
      if(fenced)flushCode();
    }
    function select(id,focus=false){active=id;for(const item of rendered){const box=boxes.get(item.id);if(box&&M.roles.includes(item.role))decorate(box,item.role,item.id===id);}
      if(focus)boxes.get(id)?.focus({preventScroll:true});updateMode();
    }
    function reveal(id){const box=boxes.get(id);if(!box)return;const area=host.getBoundingClientRect(),rect=box.getBoundingClientRect();
      if(rect.top<area.top+8||rect.bottom>area.bottom-8){host.scrollTop+=rect.top-area.top-12;return true;}return false;
    }
    function isExpanded(item){const style=M.card(getSettings(),item.role);return !style.expandable||(hasSearch()&&item.members.includes(matches[matchIndex]))||(manual.get(item.id)??restored.get(item.id)??style.default_expanded);}
    function toggle(id,keyboard=false){const item=rendered.find(i=>i.id===id);if(!item||!M.roles.includes(item.role)||!M.card(getSettings(),item.role).expandable)return;
      if(keyboard&&reveal(id))return;
      if(hasSearch()&&item.members.includes(matches[matchIndex])){say('This match stays expanded while search is open. Esc closes search.');return;}
      const box=boxes.get(id),position=box?.getBoundingClientRect().top;manual.set(id,!isExpanded(item));render();
      const next=boxes.get(id);if(next&&position!==undefined)host.scrollTop+=next.getBoundingClientRect().top-position;select(id,keyboard);
    }
    function render(){
      const scroll=host.scrollTop;boxes=new Map();cardsHost.replaceChildren();
      rendered=M.groups(session.items,getSettings(),hasSearch()?matches[matchIndex]:null);
      if(!session.items.length)cardsHost.append(empty.cloneNode(true));
      if(active&&!rendered.some(i=>i.id===active))active=null;
      for(const item of rendered){
        if(item.role==='notice'){const notice=el('div','session-notice',item.text);cardsHost.append(notice);continue;}
        const style=M.card(getSettings(),item.role),right=['question','reply'].includes(item.role),opened=isExpanded(item);
        const wrap=el('div',`card-wrap${right?' right':''}`);if(style.title_visible&&style.title)wrap.append(el('div','card-title',style.title));
        const box=el('div',`card ${item.role}${opened?'':' collapsed'}`);box.dataset.id=item.id;box.tabIndex=0;box.setAttribute('aria-label',`${labels[item.role]}: ${item.text.slice(0,120)}`);
        if(style.expandable)box.setAttribute('aria-expanded',String(opened));
        box.style.maxWidth=`${style.max_width}%`;if(!right)box.style.width=`${style.max_width}%`;
        box.style.padding=`${style.padding_y*.5*1.7}em ${style.padding_x}ch`;decorate(box,item.role,active===item.id);
        box.addEventListener('focus',()=>select(item.id));box.addEventListener('click',()=>select(item.id));
        box.addEventListener('dblclick',event=>{if(event.target===box&&!window.getSelection()?.toString())toggle(item.id);});
        const content=el('div','card-content');
        if(item.role==='tools'){
          const button=el(style.expandable?'button':'div','tool-toggle',`${style.expandable?(opened?'[−] ':'[+] '):''}${item.actions||1} actions${item.failed?' · failed':''}`);
          if(style.expandable)button.addEventListener('click',()=>toggle(item.id));content.append(button);
          if(opened){const body=el('pre','tool-body');highlight(body,item.text);content.append(body);}
        }else{
          if(style.expandable){const marker=el('span','fold-state',opened?'▾':'▸');marker.setAttribute('aria-hidden','true');box.append(marker);}
          if(opened){if(right)highlight(content,item.text);else markdown(content,item.text);}else highlight(content,item.text.split('\n').find(line=>line.trim())||'');
        }
        box.append(content);wrap.append(box);cardsHost.append(wrap);boxes.set(item.id,box);
      }
      host.scrollTop=scroll;updateMode();updateScroll();
    }
    function updateMode(){
      if(browsing||hasSearch()||helpOpen||preview.remaining()||!$('#menu').hidden)hideCommandSuggestions();
      $('#shortcut-help').hidden=!helpOpen;
      const context=$('#footer-context');context.textContent=hasSearch()?`${matches.length?matchIndex+1:0}/${matches.length} · excerpt`:'Preview';
      const style=getComputedStyle(host),columns=Math.max(12,Math.floor(($('.footer-line').clientWidth-context.offsetWidth-24)/(parseFloat(style.fontSize)*.61)));
      const hint=M.footer({columns,browsing,searchMode:searchOpen?'editing':searchReading?'reading':'closed',query,matches:matches.length,filter,
        hasDraft:!!$('#command-input').value,working:!!preview.remaining(),help:helpOpen,
        scrolled:host.scrollHeight-host.scrollTop-host.clientHeight>50,mode:M.cardMode(getSettings())});
      const label=$('#mode-label');label.replaceChildren();
      for(const part of hint.split(/(ctrl\+arrows|ctrl\+end|ctrl\+p|ctrl\+n|ctrl\+c|shift\+f4|enter|esc|tab|↑↓|\?)/g)){
        if(part==='?'){const button=el('button','footer-key',part);button.type='button';button.setAttribute('aria-label','Keyboard shortcuts');button.addEventListener('click',toggleHelp);label.append(button);}
        else label.append(el('span',/^(ctrl\+|shift\+|enter$|esc$|tab$|↑↓$)/.test(part)?'footer-key':'',part));
      }
    }
    function updateScroll(){
      $('#bottom-button').hidden=host.scrollHeight-host.scrollTop-host.clientHeight<50;
      const top=host.getBoundingClientRect().top;let question=null;
      for(const item of rendered){if(item.role==='question'){const rect=boxes.get(item.id)?.getBoundingClientRect();if(rect&&rect.bottom<top)question=item;else if(rect&&rect.top>=top)break;}}
      const pin=$('#pinned-question');pin.hidden=!question;
      if(question){pin.textContent=question.text.split('\n').find(line=>line.trim())||'';pin.dataset.id=question.id;const style=M.card(getSettings(),'question');decorate(pin,'question',false);pin.style.padding=`${style.padding_y*.5*1.7}em ${style.padding_x}ch`;
        const padding=getComputedStyle(host);pin.style.top=`${host.offsetTop}px`;pin.style.right=padding.paddingRight;pin.style.maxWidth=`${(host.clientWidth-parseFloat(padding.paddingLeft)-parseFloat(padding.paddingRight))*style.max_width/100}px`;}
      updateMode();
    }
    function bottom(){host.scrollTop=host.scrollHeight;updateScroll();}
    function browse(){helpOpen=false;if(hasSearch())closeSearch();browsing=!browsing;if(browsing){
      if(!active){const top=host.getBoundingClientRect().top;active=rendered.find(i=>boxes.get(i.id)?.getBoundingClientRect().bottom>=top)?.id||rendered.find(i=>M.roles.includes(i.role))?.id;}
      if(active)select(active,true);else host.focus();
    }else $('#command-input').focus();updateMode();}
    function displayMode(){
      if(hasSearch()||!$('#menu').hidden){say('Close search or /custom before changing card display.');return;}
      const focused=document.activeElement,previous=rendered.find(item=>item.id===active);
      changeSettings(M.nextCardMode(getSettings()));render();
      if(previous&&!active)select(rendered.find(item=>item.turn===previous.turn&&item.role==='answer')?.id
        ||rendered.find(item=>item.turn===previous.turn&&item.role==='question')?.id||null);
      if(focused?.isConnected&&focused.matches('input,textarea,select'))focused.focus({preventScroll:true});
      else if(browsing&&active)select(active,true);else host.focus({preventScroll:true});
      updateMode();say(`Cards: ${M.cardMode(getSettings())}.`);
    }
    function openSearch(){helpOpen=false;searchOpen=true;searchReading=false;$('#search-panel').hidden=false;find(false);$('#search-input').focus();$('#search-input').select();}
    function closeSearch(){searchOpen=false;searchReading=false;$('#search-panel').hidden=true;render();if(browsing&&active)select(active,true);else host.focus();}
    function acceptSearch(){searchOpen=false;searchReading=true;$('#search-panel').hidden=true;render();host.focus({preventScroll:true});}
    function find(reset=true){query=$('#search-input').value;matches=M.search(session.items,query,filter);if(reset)matchIndex=Math.max(0,matches.length-1);else matchIndex=(matchIndex+matches.length)%Math.max(1,matches.length);
      render();if(matches.length){const group=rendered.find(i=>i.members.includes(matches[matchIndex]));if(group){select(group.id);reveal(group.id);}}
    }
    function nextMatch(delta){matchIndex+=delta;find(false);}
    function toggleHelp(){if(hasSearch())closeSearch();browsing=false;helpOpen=!helpOpen;updateMode();$('#command-input').focus({preventScroll:true});}
    function stopPreview(message){preview.stop();clearInterval(previewTimer);previewTimer=null;lastRemaining=null;$('#working-preview').hidden=true;statusChanged();updateScroll();if(message)say(message);}
    function finishPreview(){
      const follow=host.scrollHeight-host.scrollTop-host.clientHeight<50;
      preview.stop();clearInterval(previewTimer);previewTimer=null;lastRemaining=null;
      $('#working-preview').dataset.state='worked';$('#working-preview').setAttribute('aria-label','Completed preview');
      $('#working-label').textContent='Worked for 7s';$('#working-label').dataset.shimmer='false';$('#working-countdown').hidden=true;
      $('#working-note').textContent='Preview complete · no prompt sent or answer generated';
      statusChanged();if(follow)bottom();else updateScroll();say('7-second preview finished. No prompt was sent and no answer was generated.');
    }
    function tickPreview(){const remaining=preview.remaining();if(!remaining){finishPreview();return;}
      if(remaining!==lastRemaining){lastRemaining=remaining;$('#working-countdown').textContent=`${7-remaining}s · ${remaining}s remaining`;}}
    function startPreview(){
      if(!preview.start()){say('Working preview is already running. Your draft is kept.');return false;}
      const follow=host.scrollHeight-host.scrollTop-host.clientHeight<50;
      clearInterval(previewTimer);lastRemaining=null;helpOpen=false;
      const status=$('#working-preview');status.dataset.state='working';status.dataset.startedAt=String(performance.now());status.setAttribute('aria-label','Working preview');status.hidden=false;
      $('#working-label').textContent='Working';$('#working-label').dataset.shimmer='false';$('#working-countdown').hidden=false;
      $('#working-note').textContent='Preview only · no model call or answer generation';
      tickPreview();previewTimer=setInterval(tickPreview,100);statusChanged();if(follow)bottom();else updateScroll();return true;
    }
    function listFiles(){const list=$('#session-list');list.replaceChildren();const needle=$('#session-filter').value.toLocaleLowerCase();
      for(const [index,file] of files.entries()){const path=file.webkitRelativePath||file.name;if(![path,file.title,file.cwd].filter(Boolean).join(' ').toLocaleLowerCase().includes(needle))continue;
        const button=el('button','session-file');button.append(el('strong','session-name',file.title||path));
        if(file.local)button.append(el('small','session-details',[file.project,new Date(file.modified).toLocaleDateString(undefined,{month:'short',day:'numeric',year:'numeric'})].filter(Boolean).join(' · ')));
        button.title=[file.title,file.cwd,path].filter(Boolean).join('\n');button.setAttribute('aria-current',String(file===selectedFile));button.addEventListener('click',()=>load(index));list.append(button);}
      if(!list.childElementCount)list.append(el('p','muted',files.length?'No matching sessions.':local?'No local sessions found.':'No files selected.'));
    }
    async function readFileWindow(file,before){
      if(file.handle)file=await file.handle.getFile();
      const end=before??file.size,start=Math.max(0,end-1024*1024),raw=new Uint8Array(await file.slice(start,end).arrayBuffer());
      const first=start?raw.indexOf(10)+1:0,base=first?start+first:start;
      return {source:start&&!first?'':new TextDecoder().decode(raw.subarray(first)),base,
        window:{before:base===end?start:base,end,total:file.size,has_older:start>0,shortened:0,skipped:start&&!first?1:0}};
    }
    function updatePageControls(){
      $('#excerpt-nav').hidden=!selectedFile;
      $('#earlier-excerpt').disabled=!pageWindow?.has_older;
      $('#newer-excerpt').disabled=!pageHistory.length;
      $('#latest-excerpt').disabled=pageCursor===null;
    }
    async function load(index,{before=null,history=[]}={}){const file=files[index];if(!file)return;
      const generation=++loadGeneration;loadController?.abort();loadController=new AbortController();stopPreview();
      say('Loading a short conversation excerpt…');
      try{
        const page=file.local?await (await localRequest('/api/session/'+file.id+(before===null?'':'?before='+before),loadController.signal)).json():await readFileWindow(file,before);
        if(generation!==loadGeneration)return;
        const parsed=PlaygroundSessions.parse(page.source,file.name,2*1024*1024,page.base||0),limited=M.excerpt(parsed.items);
        pageWindow=page.window;pageCursor=before;pageHistory=history;
        if(limited.discarded&&Number.isInteger(limited.items[0]?.sourceOffset)){pageWindow.before=limited.items[0].sourceOffset;pageWindow.has_older=pageWindow.before>0;}
        searchOpen=false;searchReading=false;helpOpen=false;$('#search-panel').hidden=true;query='';matches=[];matchIndex=0;$('#search-input').value='';
        session={...parsed,items:limited.items};selectedFile=file;active=null;browsing=false;manual.clear();restored.clear();for(const [key,value] of M.restoredAnswers(session.items))restored.set(key,value);
        empty.querySelector('p').textContent='No conversation messages in this excerpt. Use Earlier to move back.';
        $('#excerpt-note').textContent=`${limited.characters.toLocaleString()} characters${limited.shortened||pageWindow.shortened?' · some text shortened':''}${pageWindow.skipped||parsed.stats.malformed?' · some records omitted':''}`;
        $('#reload-session').disabled=false;updatePageControls();listFiles();render();bottom();host.focus({preventScroll:true});
        if(file.local){try{sessionStorage.setItem('codux.playground.lastLocal',file.id);}catch(_){}}
        say('Only this excerpt is loaded. Search and copy apply to the displayed excerpt.');
      }catch(error){if(generation===loadGeneration&&error.name!=='AbortError')say(error.message||'Could not read this excerpt.');}
    }
    function importFiles(selected,{truncated=false}={}){const incoming=Array.from(selected).filter(f=>/\.jsonl$/i.test(f.name)).sort((a,b)=>b.name.localeCompare(a.name));
      ++pickerGeneration;
      if(!incoming.length){say(truncated?'Folder scan limit reached. Choose the sessions folder or a dated subfolder.':'No .jsonl sessions found. Choose the default sessions folder shown above.');return;}
      ++libraryGeneration;$('#refresh-library').disabled=false;files=incoming;
      if(!local){$('#library-path').hidden=!truncated;$('#library-path').textContent=truncated?'Limited folder scan. Choose a dated subfolder for more sessions.':'';$('#library-path').title=$('#library-path').textContent;}
      listFiles();load(0);
    }
    async function chooseFolder(){
      if(!window.showDirectoryPicker){$('#folder').click();return;}
      const generation=++pickerGeneration;
      try{
        const directory=await window.showDirectoryPicker({id:'codux-sessions',mode:'read',...(lastDirectory?{startIn:lastDirectory}:{})});
        if(generation!==pickerGeneration)return;lastDirectory=directory;say('Finding session files in the selected folder…');
        const result=await PlaygroundSessions.directoryFiles(directory,{cancelled:()=>generation!==pickerGeneration});
        if(generation!==pickerGeneration)return;
        $('#session-picker-memory').textContent=`Selected folder: ${directory.name}. Open folder can return here next time.`;
        importFiles(result.files,result);
      }catch(error){if(generation===pickerGeneration&&error.name!=='AbortError')say('Could not read that folder. Try Open sessions, or choose the sessions folder again.');}
    }
    async function chooseFiles(){
      if(!window.showOpenFilePicker){$('#files').click();return;}
      const generation=++pickerGeneration;
      try{
        const handles=await window.showOpenFilePicker({id:'codux-sessions',multiple:true,
          types:[{description:'Codex sessions',accept:{'text/plain':['.jsonl']}}],...(lastDirectory?{startIn:lastDirectory}:{})});
        if(generation===pickerGeneration)importFiles(handles.map(handle=>({name:handle.name,handle})));
      }catch(error){if(generation===pickerGeneration&&error.name!=='AbortError')say('Could not open the file picker. Try Open folder or drag a .jsonl session into the preview.');}
    }
    if(!local){
      const location=PlaygroundSessions.sessionLocation(navigator.userAgentData?.platform||navigator.platform||navigator.userAgent);
      $('#session-path').value=location.path;
      $('#session-path-help').textContent=`Open folder, press ${location.shortcut}, paste this path, then press Enter.`;
      $('#session-picker-memory').hidden=!window.showDirectoryPicker;
      $('#session-path').addEventListener('click',event=>event.target.select());
      $('#copy-session-path').addEventListener('click',async()=>{
        try{await navigator.clipboard.writeText($('#session-path').value);say(`Path copied. Open folder, press ${location.shortcut}, paste, then press Enter.`);}
        catch(_){$('#session-path').focus();$('#session-path').select();say('Copy the selected path, then paste it into the folder picker.');}
      });
    }
    async function localRequest(path,signal){
      const response=await fetch(path,{headers:{'X-Codux-Local':local.token},cache:'no-store',credentials:'omit',mode:'same-origin',signal});
      if(!response.ok){const error=await response.json().catch(()=>({}));throw Error(error.error||'Local server unavailable. Restart the playground and refresh this page.');}
      return response;
    }
    async function refreshLibrary(autoOpen=false){
      if(!local)return;const generation=++libraryGeneration;say('Finding local conversations…');$('#refresh-library').disabled=true;
      try{
        const result=await (await localRequest('/api/sessions')).json();if(generation!==libraryGeneration)return;
        const previous=selectedFile;
        files=result.sessions.map(file=>({...file,local:true}));
        if(previous?.local)selectedFile=files.find(file=>file.id===previous.id)||previous;
        $('#reload-session').disabled=!files.includes(selectedFile);
        $('#library-path').textContent=result.root;$('#library-path').title=result.root;$('#library-path').hidden=false;
        empty.querySelector('p').textContent=files.length?'Choose a conversation from Sessions.':'No conversations found in your Codex sessions folder.';
        listFiles();
        if(autoOpen&&files.length){let recent;try{recent=sessionStorage.getItem('codux.playground.lastLocal');}catch(_){}
          await load(Math.max(0,files.findIndex(file=>file.id===recent)));
        }else{if(!session.items.length)render();say(`${files.length} local conversations available.`);}
      }catch(error){if(generation===libraryGeneration){empty.querySelector('p').textContent='The local server is unavailable. Restart it and refresh this page.';if(!session.items.length)render();say(error.message);}}
      finally{if(generation===libraryGeneration)$('#refresh-library').disabled=false;}
    }
    $('#refresh-library').addEventListener('click',()=>refreshLibrary(!session.items.length));
    $('#files-button').addEventListener('click',chooseFiles);$('#folder-button').addEventListener('click',chooseFolder);
    for(const id of ['files','folder'])$('#'+id).addEventListener('change',event=>{importFiles(event.target.files);event.target.value='';});
    $('#session-filter').addEventListener('input',listFiles);$('#reload-session').addEventListener('click',()=>load(files.indexOf(selectedFile)));
    $('#earlier-excerpt').addEventListener('click',()=>{if(pageWindow?.has_older)load(files.indexOf(selectedFile),{before:pageWindow.before,history:[...pageHistory,pageCursor]});});
    $('#newer-excerpt').addEventListener('click',()=>{if(pageHistory.length){const history=[...pageHistory],before=history.pop();load(files.indexOf(selectedFile),{before,history});}});
    $('#latest-excerpt').addEventListener('click',()=>load(files.indexOf(selectedFile)));
    $('#search-input').addEventListener('input',()=>find());
    $('#bottom-button').addEventListener('click',bottom);$('#pinned-question').addEventListener('click',()=>{const id=$('#pinned-question').dataset.id;select(id,true);reveal(id);});
    host.addEventListener('scroll',updateScroll,{passive:true});window.addEventListener('resize',updateScroll);
    host.addEventListener('dragover',event=>event.preventDefault());host.addEventListener('drop',event=>{event.preventDefault();importFiles(event.dataTransfer.files);});
    function hideCommandSuggestions(){
      $('#command-suggestions').hidden=true;$('#command-input').removeAttribute('aria-activedescendant');$('#command-input').removeAttribute('aria-describedby');
    }
    function updateCommandSuggestions(){
      const draft=$('#command-input');
      const visible=document.activeElement===draft&&!composingCommand&&!browsing&&!hasSearch()&&!helpOpen&&!preview.remaining()&&$('#menu').hidden
        &&dismissedCommand!==draft.value&&M.commandSuggestion(draft.value,draft.selectionStart,draft.selectionEnd);
      if(!visible){hideCommandSuggestions();return;}
      $('#command-suggestions').hidden=false;draft.setAttribute('aria-activedescendant','custom-suggestion');draft.setAttribute('aria-describedby','command-completion-help');
    }
    function completeCommand(submit=false){
      const draft=$('#command-input');draft.value='/custom ';draft.setSelectionRange(draft.value.length,draft.value.length);
      draft.dispatchEvent(new Event('input'));hideCommandSuggestions();if(submit)$('#command').requestSubmit();
    }
    $('#custom-suggestion').addEventListener('pointerdown',event=>{if(event.button===0)event.preventDefault();});
    $('#custom-suggestion').addEventListener('click',()=>{if(!$('#command-suggestions').hidden)completeCommand(true);});
    $('#command').addEventListener('submit',event=>{event.preventDefault();hideCommandSuggestions();const draft=$('#command-input'),command=draft.value.trim();
      if(!command)return;
      if(preview.remaining()){say('Wait for the Working preview to finish, or press Ctrl+C. Your draft is kept.');return;}
      if(hasSearch())closeSearch();helpOpen=false;browsing=false;
      if(command==='/custom'){draft.value='';openCustom();}else if(startPreview())draft.value='';
      draft.dispatchEvent(new Event('input'));});
    $('#command-input').addEventListener('keydown',event=>{
      if(!$('#command-suggestions').hidden){const completion=M.commandSuggestionAction(event);if(completion){event.preventDefault();
        if(completion==='dismiss'){dismissedCommand=event.target.value;hideCommandSuggestions();}
        else if(completion==='complete'||completion==='submit')completeCommand(completion==='submit');return;}}
      const action=M.composerAction(event,event.target.value);if(!action)return;event.preventDefault();
      if(action==='help')toggleHelp();else if(action!=='ignore')$('#command').requestSubmit();});
    $('#command-input').addEventListener('input',event=>{helpOpen=false;dismissedCommand=null;event.target.style.height='auto';event.target.style.height=Math.min(160,event.target.scrollHeight)+'px';updateMode();updateCommandSuggestions();});
    $('#command-input').addEventListener('compositionstart',()=>{composingCommand=true;hideCommandSuggestions();});
    $('#command-input').addEventListener('compositionend',()=>{composingCommand=false;updateCommandSuggestions();});
    for(const event of ['focus','click','select','keyup'])$('#command-input').addEventListener(event,updateCommandSuggestions);
    $('#command-input').addEventListener('blur',hideCommandSuggestions);
    const terminal=$('.terminal');
    const composerSize=new ResizeObserver(()=>{const promptBottom=$('#command').offsetHeight+$('#search-panel').offsetHeight+$('.terminal-footer').offsetHeight;
      terminal.style.setProperty('--prompt-bottom',promptBottom+'px');terminal.style.setProperty('--composer-height',promptBottom+'px');updateScroll();});
    for(const element of [terminal,$('#command'),$('#search-panel'),$('.terminal-footer')])composerSize.observe(element);
    document.addEventListener('visibilitychange',()=>{if(previewTimer)tickPreview();});
    window.addEventListener('pagehide',()=>stopPreview());
    document.addEventListener('keydown',event=>{
      if(event.defaultPrevented||event.isComposing)return;
      if(!event.target.closest('.terminal'))return;
      if(!$('#menu').hidden)return;
      if(event.ctrlKey&&!event.altKey&&!event.metaKey&&event.key.toLowerCase()==='c'&&preview.remaining()&&!window.getSelection()?.toString()){
        const input=event.target;if(!input.matches('input,textarea')||input.selectionStart===input.selectionEnd){event.preventDefault();stopPreview('Working preview stopped. No prompt was sent.');return;}}
      if(helpOpen&&event.key==='Escape'){event.preventDefault();helpOpen=false;updateMode();return;}
      const action=M.keyAction(event,{browsing,searchOpen,searchReading,matches:matches.length,searchInput:event.target===$('#search-input'),
        selection:!!window.getSelection()?.toString(),
        editable:event.target.matches('input,textarea,select')||event.target.isContentEditable,card:event.target.classList.contains('card'),button:!!event.target.closest('button,a')});
      if(!action)return;event.preventDefault();
      if(action==='escape'){if(searchOpen)closeSearch();else if(searchReading){closeSearch();bottom();}else if(browsing)browse();else bottom();}
      else if(action==='search')openSearch();
      else if(action.endsWith('-match'))nextMatch(action==='previous-match'?-1:1);
      else if(action.endsWith('-filter')){filter=M.filters[(M.filters.indexOf(filter)+(action==='previous-filter'?4:1))%M.filters.length];find();}
      else if(action==='browse')browse();
      else if(action==='bottom')bottom();
      else if(action==='card-mode')displayMode();
      else if(action==='accept-search')acceptSearch();
      else if(action==='fold')toggle(active,true);
      else if(action.startsWith('card-')){select(M.navigate(rendered,active,action.slice(5)),true);reveal(active);}
      else if(action.startsWith('scroll-')){
        const key=action.slice(7);if(key==='Home')host.scrollTop=0;else if(key==='End')bottom();else host.scrollBy({top:(key.includes('Up')?-1:1)*(key.startsWith('Page')?host.clientHeight*.85:28),behavior:'instant'});
      }
    });
    if(local)refreshLibrary(true);
    return {render,setOuter(value){outer=value;},isWorking:()=>!!preview.remaining(),reset(){manual.clear();active=null;render();},getSession(){return session;}};
  };
})(globalThis);
