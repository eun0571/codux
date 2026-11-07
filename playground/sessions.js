/* Read-only Codex rollout importer. No network, file writes, or HTML evaluation. */
(function(root){
  'use strict';
  const kind = value => String(value||'').replace(/[_-]/g,'').toLowerCase();
  function text(value) {
    if(typeof value==='string')return value;
    if(Array.isArray(value))return value.map(text).filter(Boolean).join('\n');
    if(!value || typeof value!=='object')return '';
    if(typeof value.text==='string')return value.text;
    if(value.type==='image' || /image/i.test(value.type||''))return '[Image attachment]';
    return '';
  }
  function decode(value){try{return typeof value==='string'?JSON.parse(value):value;}catch{return null;}}
  function answerText(body){return body.match(/<proposed_plan>([\s\S]*?)<\/proposed_plan>/)?.[1].trim()??body;}
  function formReply(value){
    value=value.trim();
    if(value.startsWith('# Context from my IDE setup:\n'))value=value.split('\n## My request for Codex:\n').at(-1).trim();
    const match=value.match(/^<send_user_message_question_reply>([\s\S]*?)<\/send_user_message_question_reply>$/);
    const data=match&&decode(match[1]);
    const rows=Array.isArray(data)?data:data?[data]:[];
    return rows.length&&rows.every(row=>row&&['questionItemId','question','answer'].every(key=>typeof row[key]==='string'))
      ?rows.map(row=>`> ${row.question}\n\n${row.answer}`).join('\n\n'):null;
  }
  function parse(source, name='Session', maxBytes=64*1024*1024, baseOffset=0) {
    if(typeof source!=='string')throw Error('Expected a JSONL session file.');
    if(source.length>maxBytes)throw Error(`Session exceeds the ${Math.floor(maxBytes/1024/1024)} MB viewer limit.`);
    const records=[], stats={malformed:0,ignored:0,duplicates:0};
    const preferences=new Map(); let turn='start', meta={name}, sequence=0;
    const promote=(turn,category,rank)=>{const key=turn+':'+category;preferences.set(key,Math.max(preferences.get(key)||0,rank));};
    let byteOffset=baseOffset+(source.startsWith('\uFEFF')?3:0);const encoder=new TextEncoder();
    for(const line of source.replace(/^\uFEFF/,'').split('\n')){
      const lineOffset=byteOffset;byteOffset+=encoder.encode(line).length+1;
      if(!line.trim())continue;
      let r;try{r=JSON.parse(line);}catch{stats.malformed++;continue;}
      if(!r||typeof r!=='object')continue;
      if(!Number.isInteger(r.preview_offset))r.preview_offset=lineOffset;
      const p=r?.payload;if(!p || typeof p!=='object')continue;
      if(r.type==='session_meta') {meta={name,id:p.id||p.session_id,cwd:p.cwd,version:p.cli_version,timestamp:p.timestamp||r.timestamp};continue;}
      // Excerpts often start after task_started. Every canonical event carries
      // the turn ID; response_item copies inherit it instead of creating a
      // second, synthetic turn. A context refresh alone is not a new turn.
      const starts=p.type==='task_started'||p.type==='turn_started';
      if(p.turn_id){
        if(turn==='start'&&!starts)for(const previous of records)previous.turn=p.turn_id;
        turn=p.turn_id;
      }else if(starts)turn=`turn-${++sequence}`;
      const row={r,p,turn:p.turn_id||turn,index:records.length}; records.push(row);
    }
    // Build precedence only after the leading partial turn has been resolved.
    for(const row of records){
      const {r,p}=row;
      if(r.type==='event_msg' && p.type==='item_completed') {
        const k=kind(p.item?.type);
        if(k==='usermessage')promote(row.turn,'user',3);
        if(k==='agentmessage'||k==='plan')promote(row.turn,'assistant',3);
        if(['commandexecution','filechange','mcpToolCall'.toLowerCase(),'dynamictoolcall','websearch','imageview','extension'].includes(k))promote(row.turn,'tools',3);
      }
      if(r.type==='event_msg' && ['user_message','agent_message'].includes(p.type))promote(row.turn,p.type==='user_message'?'user':'assistant',2);
    }
    const items=[], seen=new Map(), calls=new Map();
    const add=(role,body,row,extra={})=>{
      if(typeof body!=='string'){stats.ignored++;return null;}
      if(!body.trim())return null;
      const key=extra.sourceId?`${row.turn}:${role}:${extra.sourceId}`:null;
      if(key&&seen.has(key)){stats.duplicates++;return seen.get(key);}
      const item={id:`entry-${items.length}`,role,text:body,turn:row.turn,timestamp:row.r.timestamp,sourceOffset:row.r.preview_offset,...extra};
      items.push(item);if(key)seen.set(key,item);return item;
    };
    const allowed=(row,category,rank)=>(preferences.get(row.turn+':'+category)||1)<=rank;
    function message(row,role,body,phase,id,questions){
      if(typeof body!=='string')body=text(body);
      if(role==='user') {
        const reply=formReply(body);
        const looksLikeContext=/^(?:# AGENTS\.md instructions|<environment_context>|<INSTRUCTIONS>)/.test(body.trim());
        if(looksLikeContext){stats.ignored++;return;}
        // Native Codux marks explicit question-form replies, not every prompt
        // following an assistant question.
        add(reply!==null?'reply':'question',reply??body,row,{sourceId:id});
      } else {
        const asks=Array.isArray(questions)&&questions.length>0;
        if(asks){
          const prompts=questions.map(q=>q.title||q.question||'').filter(q=>q&&!body.includes(q));
          body=[body,...prompts].filter(Boolean).join('\n\n');
        }
        add(asks||phase==='commentary'||phase==='analysis'?'intermediate':'answer',answerText(body),row,{sourceId:id});
      }
    }
    for(const row of records){
      const {r,p}=row;
      if(r.type==='event_msg'&&p.type==='item_completed'){
        const it=p.item||{},k=kind(it.type),body=text(it.content)||it.text||it.message||'';
        if(k==='usermessage')message(row,'user',body,null,it.id);
        else if(k==='agentmessage')message(row,'assistant',body,it.phase,it.id,it.questions);
        else if(k==='plan')add('answer',answerText(it.text||body),row,{sourceId:it.id});
        else if(k==='contextcompaction')add('notice','Context compacted',row);
        else if(k==='commandexecution')add('tools',`Ran ${Array.isArray(it.command)?it.command.join(' '):it.command||'command'}\n${it.aggregated_output||''}`,row,{actions:1,sourceId:it.id,failed:it.status==='failed'||Number(it.exit_code)>0});
        else if(k==='filechange')add('tools',`Edited files\n${JSON.stringify(it.changes||[],null,2)}\n${it.stdout||''}${it.stderr||''}`,row,{actions:1,sourceId:it.id,failed:it.status==='failed'});
        else if(['mcptoolcall','dynamictoolcall','websearch','imageview','extension'].includes(k))add('tools',`${it.tool||it.kind||it.type}\n${it.query||it.path||''}\n${JSON.stringify(it.result||it.results||it.content_items||it.content||it.action||'',null,2)}`,row,{actions:1,sourceId:it.id,failed:it.status==='failed'||it.success===false});
        else if(k!=='reasoning')stats.ignored++;
      } else if(r.type==='event_msg'&&['user_message','agent_message'].includes(p.type)){
        const role=p.type==='user_message'?'user':'assistant';
        if(allowed(row,role,2))message(row,role,p.message||'',p.phase,p.client_id||p.id,p.questions);
      } else if(r.type==='response_item'&&p.type==='message'){
        if(['user','assistant'].includes(p.role)&&p.channel!=='analysis'&&allowed(row,p.role,1))message(row,p.role,text(p.content),p.phase||p.channel,p.id,p.questions);
      } else if(r.type==='response_item'&&['function_call','custom_tool_call'].includes(p.type)){
        if(/request_user_input/.test(p.name||'')){
          const input=decode(p.arguments||p.input),questions=input?.questions;
          if(Array.isArray(questions)){add('intermediate',questions.map(q=>q.question||q.title||'').join('\n'),row,{sourceId:p.call_id});calls.set(p.call_id,{question:true});}
        } else if(allowed(row,'tools',1)){
          const item=add('tools',`${p.name||'Tool'}\n${p.arguments||p.input||''}`,row,{actions:1,sourceId:p.call_id||p.id});
          if(item)calls.set(p.call_id,item);
        }
      } else if(r.type==='response_item'&&['function_call_output','custom_tool_call_output'].includes(p.type)){
        const call=calls.get(p.call_id);
        if(call?.question){const output=decode(p.output);if(output?.answers){add('reply',Object.entries(output.answers).map(([key,v])=>`${key}: ${text(v.answers||v.answer)||JSON.stringify(v)}`).join('\n'),row);}}
        else if(call)call.text+='\n'+(text(p.output)||JSON.stringify(p.output));
      } else if(r.type==='event_msg'&&['task_complete','turn_complete'].includes(p.type)){
        const last=typeof p.last_agent_message==='string'?answerText(p.last_agent_message):'';
        const existing=items.findLast(i=>i.turn===row.turn&&['answer','intermediate'].includes(i.role)&&i.text===last);
        // Canonical histories already contain the final message. Completion is
        // metadata, and may hold a differently clipped copy of that same text.
        if(last&&!existing&&(preferences.get(row.turn+':assistant')||0)<3)add('answer',last,row);
      } else if(r.type==='event_msg'&&['turn_aborted','error','warning'].includes(p.type))add('notice',p.message||p.reason||'Turn interrupted',row);
      else if(r.type==='compacted'&&!records.some(x=>x.turn===row.turn&&kind(x.p.item?.type)==='contextcompaction'))add('notice','Context compacted',row);
    }
    // Native Codux retains only the last final-answer candidate before each new prompt.
    let candidate=null;
    for(const item of items){if(item.role==='question')candidate=null;else if(item.role==='answer'){if(candidate)candidate.role='intermediate';candidate=item;}}
    return {meta,items,stats};
  }
  function firstPrompt(value){
    if(typeof value!=='string')return '';
    value=value.trim();
    if(value.startsWith('# Context from my IDE setup:')){
      const marker='## My request for Codex:';
      if(!value.includes(marker))return '';
      value=value.slice(value.indexOf(marker)+marker.length).trim();
    }
    if(/^(?:# AGENTS\.md|<environment_context>|<INSTRUCTIONS>|<send_user_message_question_reply>)/.test(value))return '';
    return Array.from(value.replace(/\s+/g,' ')).slice(0,160).join('');
  }
  function metadata(source){
    const result={};
    for(const line of source.replace(/^\uFEFF/,'').split('\n')){
      const row=decode(line),p=row?.payload;if(!p||typeof p!=='object')continue;
      if(row.type==='session_meta'){
        if(typeof p.id==='string'||typeof p.session_id==='string')result.sessionId=String(p.id||p.session_id).toLowerCase();
        if(typeof p.cwd==='string')result.cwd=p.cwd.slice(0,1024);
      }
      if(result.firstPrompt)continue;
      let body;
      if(row.type==='event_msg'&&p.type==='user_message')body=p.message;
      else if(row.type==='event_msg'&&p.type==='item_completed'&&kind(p.item?.type)==='usermessage')body=text(p.item.content);
      else if(row.type==='response_item'&&p.type==='message'&&p.role==='user')body=text(p.content);
      const title=firstPrompt(body);if(title)result.firstPrompt=title;
    }
    return result;
  }
  function sessionId(name){return name.match(/([a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12})\.jsonl$/i)?.[1].toLowerCase();}
  async function readMetadata(file){
    const prefix=64*1024,limit=256*1024;
    let info=metadata(await file.slice(0,prefix).text());
    if(!info.firstPrompt&&file.size>prefix)info=metadata(await file.slice(0,limit).text());
    return info;
  }
  async function readTitleIndex(file){
    const limit=4*1024*1024,start=Math.max(0,file.size-limit);
    let source=await file.slice(start).text();
    if(start)source=source.includes('\n')?source.slice(source.indexOf('\n')+1):'';
    const titles=new Map();
    for(const line of source.replace(/^\uFEFF/,'').split('\n')){
      const row=decode(line);
      if(typeof row?.id!=='string'||typeof row.thread_name!=='string')continue;
      if(!/^[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}$/i.test(row.id))continue;
      const id=row.id.toLowerCase(),title=Array.from(row.thread_name.replace(/\s+/g,' ').trim()).slice(0,240).join('');
      if(title)titles.set(id,title);else titles.delete(id);
    }
    return {titles,truncated:start>0};
  }
  function importSelection(selected){
    const all=Array.from(selected),index=all.find(file=>file.name==='session_index.jsonl');
    // A selected .codex folder can contain unrelated JSONL files. Only its
    // rollout files and the explicitly recognized title index are considered.
    const files=all.filter(file=>file.name!=='session_index.jsonl'&&/\.jsonl$/i.test(file.name)
      &&(!file.webkitRelativePath||/^rollout-.*\.jsonl$/i.test(file.name)))
      .sort((a,b)=>b.name.localeCompare(a.name)).map(blob=>({blob,name:blob.name,
        webkitRelativePath:blob.webkitRelativePath,size:blob.size,sessionId:sessionId(blob.name),
        modified:blob.lastModified||null,metadataDone:false}));
    return {files,index};
  }
  // Keep title reads small and yield between batches. Replaced libraries stop
  // scheduling reads, and late results cannot update the new session list.
  async function hydrateMetadata(files,{cancelled=()=>false,apply=()=>{},names=new Map(),yieldTask=()=>new Promise(resolve=>setTimeout(resolve,0))}={}){
    const queue=files.filter(file=>!file.local&&!file.metadataDone&&!names.has(file.sessionId));let cursor=0;
    async function worker(){
      while(!cancelled()){
        const file=queue[cursor++];if(!file)return;
        let info;
        try{info=await readMetadata(file.blob);}catch(_){info={readError:true};}
        if(cancelled())return;
        Object.assign(file,info,{metadataDone:true});apply(file);await yieldTask();
      }
    }
    await Promise.all(Array.from({length:Math.min(4,queue.length)},worker));
  }
  root.PlaygroundSessions={parse,text,formReply,metadata,sessionId,readMetadata,readTitleIndex,importSelection,hydrateMetadata};
  if(typeof module!=='undefined')module.exports=root.PlaygroundSessions;
})(globalThis);
