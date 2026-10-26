#!/usr/bin/env python3
"""Build the reviewed workspace view from current seat, skill, and tool pages. Python 3.9."""
import argparse
from datetime import date
import json
import os
from pathlib import Path
import re
from urllib.parse import quote
from page_indexes import safe, walk, cell

KINDS=('cli','mcp','plugin','service','external-app','schedule')
MARKS={'live':'✅','installing':'🔄','chosen':'☑️','candidate':'⬜'}

def parse(path):
    text=path.read_text(encoding='utf-8',errors='replace')
    if text.startswith('<!-- Built by '):text=text.split('-->\n',1)[1]
    fields={};body=text
    if text.startswith('---\n') and '\n---' in text[4:]:
        end=text.index('\n---',4);lines=text[4:end].splitlines();body=text[end+4:].lstrip('\n');i=0
        if text[4:end].lstrip().startswith('{'):
            fields=json.loads(text[4:end])
            if not isinstance(fields,dict):raise ValueError('Frontmatter must be an object: '+str(path))
            title=next((s[2:] for s in body.splitlines() if s.startswith('# ')),path.stem)
            return fields,body,title
        while i<len(lines):
            m=re.match(r'^([\w-]+):\s*(.*)',lines[i])
            if not m:i+=1;continue
            key,value=m.groups();j=i+1;block=[]
            while j<len(lines) and (lines[j].startswith((' ','\t')) or not lines[j].strip() or (not value and lines[j].startswith('- '))):block.append(lines[j]);j+=1
            if value in ('>','>-','|','|-'):fields[key]=' '.join(s.strip() for s in block if s.strip())
            elif not value and block:
                if all(s.strip().startswith('- ') for s in block if s.strip()):fields[key]=[s.strip()[2:].strip('"\'') for s in block if s.strip()]
                else:fields[key]={m[1]:m[2].strip().strip('"\'') for s in block for m in [re.match(r'\s+([\w-]+):\s*(.*)',s)] if m}
            elif value.startswith('['):fields[key]=[s.strip().strip('"\'') for s in value.strip('[]').split(',') if s.strip()]
            else:
                if block and value and not value.startswith(('"',"'")):
                    value=' '.join([value]+[s.strip() for s in block if s.strip()])
                fields[key]=value.strip().strip('"\'')
            i=j
    title=next((s[2:] for s in body.splitlines() if s.startswith('# ')),path.stem)
    return fields,body,title

def sentence(text,cut=120):
    text=' '.join(str(text).split());m=re.search(r'[.!?](?= |$)',text)
    text=text[:m.end()] if m else text
    return text if len(text)<=cut else text[:cut].rsplit(' ',1)[0]+' …'

def href(target,page,label=None):
    return '[%s](%s)'%(cell(label or target.name),quote(os.path.relpath(str(target),str(page.parent)),safe='/.-_'))

def table(lines,columns,rows,empty):
    if rows:
        lines += ['| '+' | '.join(columns)+' |','|'+'|'.join('---' for _ in columns)+'|']
        lines += ['| '+' | '.join(row)+' |' for row in rows]
    else:lines += [empty]
    lines += ['']

def block(lines,label,columns,rows):
    if not rows:return
    lines += ['```',label+'  (%d)'%len(rows),'   '+'  '.join(columns)]
    for row in rows:
        text='   '+'  '.join(str(x) for x in row)
        lines += [text] if len(text)<=78 else ['   '+str(row[0])]+['      '+str(x)[:72] for x in row[1:] if x]
    lines += ['```','']

def header(ws,section,folder,page,day):
    title={'TEAM':'Team','SKILLS':'Skills','TOOLS':'Tools'}[section]
    nav={'TEAM':'**Team** · [Skills](SKILLS.md) · [Tools](TOOLS.md)',
         'SKILLS':'[Team](TEAM.md) · **Skills** · [Tools](TOOLS.md)',
         'TOOLS':'[Team](TEAM.md) · [Skills](SKILLS.md) · **Tools**'}[section]
    source=href(folder,page,str(folder)) if folder.is_dir() else '`'+str(folder)+'` (not on disk)'
    return ['<!-- Built by make_workspaces_view.py. Do not edit. -->','---','type: index','workspace: '+ws,
        'timestamp: '+day+'T00:00:00Z','---','# '+title+': '+ws,'',nav,'',
        'View of '+source+'. `base/make_workspaces_view.py` makes this page.',
        'Edit the source page, then run the script.','']

def tool_scopes(system):
    """Explicit catalog picks override historical pages; absent picks keep legacy discovery."""
    path=system/'config/tools.yaml'
    if not path.is_file():return {}
    from simple_yaml import safe_load
    data=safe_load(path.read_text(encoding='utf-8')) or {}
    return {(row.get('kind'),row.get('name')):('off' if row.get('guide_only') else row['applies_to'])
        for row in data.get('tools',[]) if isinstance(row,dict) and 'applies_to' in row}

def tool_visible(name,kind,scopes,workspace,fields=None):
    fields=fields or {};name=name.removesuffix('.local')
    scope=scopes.get((kind,name),fields.get('applies_to','global'))
    if fields.get('status')=='off':return False
    return scope=='global' or isinstance(scope,list) and workspace in scope

def tool_inventory(ws,system,include_excluded=False):
    result={};scopes=tool_scopes(system)
    for root in (system/'tools',ws/'tools'):
        for kind in KINDS:
            directory=root/kind
            if not directory.is_dir():continue
            for p in sorted(directory.glob('*.md')):
                if p.is_symlink() or not safe(p.name):continue
                d,body,title=parse(p)
                if d.get('type')!='tool':continue
                # <name>.local.md is the person's own page; it wins over the shipped <name>.md beside it.
                local=p.stem.endswith('.local');name=p.stem[:-len('.local')] if local else p.stem
                old=result.get(name)
                if not include_excluded and not tool_visible(name,kind,scopes,ws.name,d):
                    # Keep an off local override until selection ends; the shipped page must not return.
                    if local and (not old or old[0].parent==p.parent):result[name]=(p,d,body,title)
                    continue
                if not local and old and old[0].parent==p.parent and old[0].stem.endswith('.local'):continue
                result[name]=(p,d,body,title)
    if include_excluded:return result
    return {name:item for name,item in result.items()
        if tool_visible(name,item[0].parent.name,scopes,ws.name,item[1])}

def shelf(ws,system):
    """Tools that config/tools.yaml pushes to this workspace. applies_to: global, off, or a list; absent is off."""
    path=system/'config/tools.yaml'
    if not path.is_file():return []
    from simple_yaml import safe_load
    data=safe_load(path.read_text(encoding='utf-8')) or {};pushed=[]
    for tool in (data.get('tools') if isinstance(data,dict) else None) or []:
        if not isinstance(tool,dict) or 'applies_to' not in tool:continue
        if tool.get('guide_only'):continue
        scope=tool['applies_to']
        if scope not in ('global','off') and not (isinstance(scope,list) and scope and len(set(scope))==len(scope)
                and all(isinstance(x,str) and re.fullmatch(r'[a-z0-9][a-z0-9-]*',x) for x in scope)):
            raise ValueError('applies_to must be global, off, or a workspace list: '+str(tool.get('name')))
        if scope=='global' or (isinstance(scope,list) and ws.name in scope):pushed.append(tool)
    return pushed

def shelf_rows(ws,system,page,local):
    rows=[]
    for tool in shelf(ws,system):
        name=str(tool.get('name','')).strip();kind=str(tool.get('kind',''))
        if not name or name in local:continue
        target=str(tool.get('page',''));p=system/target
        good=target.startswith('tools/') and '..' not in Path(target).parts and p.is_file() and not p.is_symlink()
        d,title=(parse(p)[0],parse(p)[2]) if good else ({},name)
        if not tool_visible(name,kind,tool_scopes(system),ws.name,d):continue
        label=(MARKS.get(d.get('status'),'')+' '+href(p,page,title)).strip() if good else '`'+cell(name)+'` (no page)'
        what=sentence(d.get('what') or '(not on the page)')
        rows.append((KINDS.index(kind) if kind in KINDS else len(KINDS),name,[label,cell(kind),
            cell(what+'. Owner: '+str(tool.get('owner','person'))+'. Why: '+str(tool.get('why','(not in the list)'))+'.')]))
    return [r for _,_,r in sorted(rows)]

def seat_fields(path,system):
    """Read the current declaration; expand the applied catalog selections when present."""
    fields=parse(path)[0]
    if 'sets' in fields:
        from agent_catalog import expand
        fields=expand(fields,system/'config/catalog.yaml')
    return fields

def tool_dependencies(path,known,page,excluded=()):
    """Use declarations and command evidence. A runtime or configuration mention is not a requirement."""
    fields,body,_=parse(path);evidence={};canonical={name.casefold():name for name in known}
    def record(name,why):
        name=canonical.get(name.casefold(),name.lower())
        evidence.setdefault(name,why)
    for key in ('tools','mcpServers','requires_tools'):
        declared=fields.get(key)
        if isinstance(declared,list):
            for name in declared:
                if isinstance(name,str):record(name,'Declared in '+key)
    # A service can be required through MCP rather than through a shell command.
    mcp_required=set();plain_body=re.sub(r'\*\*|__','',body)
    configured=re.findall(r'\bMCP\s+(?:base|endpoint|url)\s*:\s*`?(https?://[^\s`<>]+)',plain_body,re.I)
    metadata=fields.get('metadata',{});metadata=metadata if isinstance(metadata,dict) else {}
    description=str(fields.get('description') or '')
    for name,(target,meta,toolbody,title) in known.items():
        tokens={name,title}
        named=any(re.search(r'(?<![\w-])'+re.escape(token)+r'\s+MCP\b',description,re.I) for token in tokens)
        endpoint=any(url in toolbody for url in configured)
        provider=str(metadata.get('author','')).casefold() in {token.casefold() for token in tokens}
        service_named=any(re.search(r'(?<![\w-])'+re.escape(token)+r'\b',description,re.I) for token in tokens)
        interface=str(metadata.get('interface','')).casefold() if provider and service_named else ''
        rest_named=any(re.search(r'(?<![\w-])'+re.escape(token)+r'\s+(?:REST(?:\s+API)?|API)\b',description,re.I) for token in tokens)
        if named or endpoint or interface in ('mcp','both'):
            detail='configured endpoint' if endpoint else 'metadata interface: '+interface if interface else 'skill description'
            record(name,title+' MCP required ('+detail+')')
            mcp_required.add(name)
        elif rest_named or interface in ('api','rest'):
            record(name,title+' REST API required ('+('metadata interface: '+interface if interface else 'skill description')+')')
    # An alternative transport is not a second mandatory dependency.
    rest=re.search(r'^#{1,6}\s+REST Fallback[^\n]*\n',body,re.M|re.I)
    if rest:
        section=body[rest.end():];end=re.search(r'^#{1,6}\s+',section,re.M)
        section=section[:end.start()] if end else section
        for name in mcp_required:
            title=known[name][3]
            if any(re.search(r'(?<![\w-])'+re.escape(token)+r'\b',section,re.I) for token in (name,title)):
                evidence[name]=title+' MCP (primary), or '+title+' REST fallback when MCP is unavailable'
    # A named CLI in the description is explicit evidence even when its tool page is absent.
    for match in re.finditer(r'\b([A-Za-z][\w.-]*)(?:[\u2019\x27]s)?\s+CLI\b',str(fields.get('description') or ''),re.I):
        named=match[1]
        if named.lower() in ('the','a','this','via','with'):continue
        command=re.search(r'^\s*'+re.escape(named)+r'\s+[^\n]+',body,re.M|re.I)
        record(named,'CLI: '+command[0].strip() if command else match[0])
    # An explicit instruction to run a shell helper can name a tool with no catalog page.
    for match in re.finditer(r'\bRun\s+`([a-z][a-z0-9-]*)\s+([^`\n]+)`',body,re.I):
        if re.search(r'\b(?:never|not|do not)\b',body[max(0,match.start()-20):match.start()],re.I):continue
        record(match[1],'CLI: '+match[1]+' '+match[2])
    # Only executable examples count as catalog evidence. Paths and runtime alternatives do not.
    section='source page';fenced=False
    for line in body.splitlines():
        heading=re.match(r'^#{1,6}\s+(.+)',line)
        if heading:section=heading[1]
        if line.startswith('```'):
            fenced=not fenced;continue
        snippets=[line.strip()] if fenced else re.findall(r'`([^`\n]+)`',line)
        for snippet in snippets:
            for name in known:
                invocation=re.match(r'^'+re.escape(name)+r'(?:\s+[^\n]+|$)',snippet,re.I)
                if not invocation:continue
                # A bare code word needs an explicit CLI label, not a passing reference.
                if snippet.casefold()==name.casefold() and not re.search(r'`'+re.escape(name)+r'`\s+CLI\b',line,re.I):continue
                conditional=bool(re.search(r'\b(adopt|optional|example|alternative|winner|if|when)\b',section+' '+line,re.I))
                why=('Conditional command' if conditional else 'Command')+' in '+section+': '+snippet
                record(name,why)
    needs=[];missing=[]
    for name,why in sorted(evidence.items()):
        if name in excluded:continue
        tool=known.get(name)
        if tool:
            target,meta,toolbody,title=tool
            purpose=re.search(r'^## (?:Purpose|What is it\?)\n+([^#\n].*)',toolbody,re.M)
            what=meta.get('what') or meta.get('description') or (purpose[1] if purpose else '(not on the page)')
            needs.append(href(target,page,title)+': '+cell(sentence(what))+
                '; '+cell(why)+' — '+href(path,page,'source'))
        else:
            missing.append(name)
            needs.append('`'+cell(name)+'`: (a tool with no page yet); '+cell(why)+' — '+href(path,page,'source'))
    return '<br>'.join(needs) or 'Not declared on the source page',missing,bool(evidence)

def render(ws,section,system,day):
    folder=ws/{'TEAM':'team','SKILLS':'skills','TOOLS':'tools'}[section]
    page=system/'workspaces'/ws.name/(section+'.md')
    lines=header(ws.name,section,folder,page,day)
    if section=='TEAM':
        seats=[p for p in sorted(folder.glob('*.md')) if p.name!='TEAM.md' and not p.is_symlink() and safe(p.name)]
        lead=next((p for p in seats if p.stem=='lead-'+ws.name),None)
        seats=([lead] if lead else [])+[p for p in seats if p!=lead]
        lines += ['```','SEATS  '+str(len(seats)),'LEAD   '+(lead.stem if lead else '(not on disk)'), 'MADE   '+day+' 00:00','```','']
        rows=[]
        for p in seats:
            d=seat_fields(p,system);skills=d.get('skills',[]);tools=d.get('tools' if 'id' in d else 'mcpServers',[])
            a=len(skills) if isinstance(skills,list) else 0;b=len(tools) if isinstance(tools,list) else 0
            rows.append([href(p,page,'`'+p.stem+'`')+(' · lead' if p==lead else ''),
                cell(d.get('summary') or d.get('description') or '(not on disk)'),
                '%d skill%s · %d tool%s'%(a,'' if a==1 else 's',b,'' if b==1 else 's')])
        table(lines,['Seat','What it does','Loads'],rows,'No seat file is in this folder yet.')
        extras=[]
        if folder.is_dir():
            for p in sorted(folder.iterdir()):
                if not safe(p.name) or p.is_symlink() or p in seats:continue
                text={'TEAM.md':'the team page of this workspace','claude':'Claude files made from the seats','codex':'Codex files made from the seats'}.get(p.name,'(not on disk)')
                extras.append((p.name+('/' if p.is_dir() else ''),text,('%d files'%sum(1 for _ in walk(p))) if p.is_dir() else ''))
        block(lines,'ALSO IN team/',['NAME','WHAT IT IS','HOLDS'],extras)
    elif section=='SKILLS':
        skills=[p for p in sorted(folder.iterdir()) if p.is_dir() and not p.is_symlink() and safe(p.name)] if folder.is_dir() else []
        known=tool_inventory(ws,system);rows=[];missing=[];missing_tools={};tool_users=0
        for skill in skills:
            p=skill/'SKILL.md'
            if not p.is_file():missing.append((skill.name,next((str(x.relative_to(skill)) for x in walk(skill)),'(empty)')));continue
            d,body,title=parse(p);use=d.get('use') or (d.get('metadata',{}).get('category','') if isinstance(d.get('metadata'),dict) else '') or 'No use yet'
            needs,unpaged,has_tools=tool_dependencies(p,known,page);tool_users+=int(has_tools)
            for name in unpaged:missing_tools.setdefault(name,set()).add(skill.name)
            rows.append((use,[href(p,page,'`'+skill.name+'`'),cell(sentence(d.get('description','(not on disk)'))),needs]))
        uses=sorted(set(u for u,_ in rows if u!='No use yet'),key=str.lower)
        lines += ['```','SKILLS       '+str(len(rows)),'USES         '+str(len(uses)),'NEED A TOOL  '+str(tool_users),
            'NO SKILL.md  '+str(len(missing)),'MADE         '+day+' 00:00','```','',
            '**Tools it needs** lists the tools that must be set up for the skill to work. Each name opens the page of the tool.','']
        for use in uses+(['No use yet'] if any(u=='No use yet' for u,_ in rows) else []):
            lines += ['## '+use,''];table(lines,['Skill','What it does','Tools it needs'],[row for u,row in rows if u==use],'No skill is in this folder yet.')
        if not rows:table(lines,['Skill','What it does','Tools it needs'],[],'No skill is in this folder yet.')
        block(lines,'NO SKILL.md',['FOLDER','HOLDS'],missing)
        block(lines,'NEEDED TOOLS WITH NO PAGE',['TOOL','NEEDED BY'],[(name,str(len(users))+' skills') for name,users in sorted(missing_tools.items())])
    else:
        rows=[];no_page=[];empty=[];on_template=0;scopes=tool_scopes(system)
        for kind in KINDS:
            directory=folder/kind
            if not directory.is_dir():continue
            entries=[p for p in sorted(directory.iterdir()) if safe(p.name) and not p.is_symlink()]
            if not entries:empty.append((kind,))
            pages={p.stem:p for p in entries if p.suffix=='.md' and p.is_file()}
            for p in entries:
                if p.is_file() and p.suffix=='.md':
                    d,body,title=parse(p)
                    if d.get('type')!='tool':no_page.append((kind,p.name));continue
                    if not tool_visible(p.stem,kind,scopes,ws.name,d):continue
                    good=all(d.get(k) for k in ('name','what','kind','use','status'))
                    on_template+=int(good);use=d.get('use','No use yet') if good else 'No use yet'
                    summary=sentence(d.get('what') or d.get('description') or '')
                    if not summary:
                        m=re.search(r'^## (?:Purpose|What is it\?)\n+([^#\n].*)',body,re.M);summary=sentence(m[1]) if m else '(not on the page)'
                    rows.append((use,kind,p.name,[MARKS.get(d.get('status'),'')+' '+href(p,page,title),kind,cell(summary)]))
                elif p.stem not in pages:no_page.append((kind,p.name+('/' if p.is_dir() else '')))
        pushed=shelf_rows(ws,system,page,{n.rsplit('.',1)[0] for _,_,n,_ in rows})
        lines += ['```','TOOL PAGES       '+str(len(rows)),'ON THE TEMPLATE  '+str(on_template),'FILES, NO PAGE   '+str(len(no_page))]
        lines += (['FROM THE SHELF   '+str(len(pushed))] if pushed else [])+['MADE             '+day+' 00:00','```','']
        uses=sorted(set(u for u,_,_,_ in rows if u!='No use yet'),key=str.lower)
        for use in uses+(['No use yet'] if any(u=='No use yet' for u,_,_,_ in rows) else []):
            lines += ['## '+use,''];table(lines,['Tool','Kind','What it is'],[r for u,k,n,r in sorted(rows,key=lambda r:(KINDS.index(r[1]),r[2])) if u==use],'No tool page is in this folder yet.')
        if not rows:table(lines,['Tool','Kind','What it is'],[],'No tool page is in this folder yet.')
        if pushed:
            lines += ['## From the shelf','','These tools live on the system shelf. `config/tools.yaml` pushes them here with `applies_to`.','']
            table(lines,['Tool','Kind','What it is'],pushed,'')
        block(lines,'FILES WITH NO PAGE',['KIND','FILE'],no_page);block(lines,'EMPTY KIND FOLDERS',['KIND'],empty)
        extras=[]
        if folder.is_dir():
            for p in sorted(folder.iterdir()):
                if p.is_file() and not p.is_symlink() and safe(p.name):extras.append((p.name,parse(p)[2][:50] if p.suffix=='.md' else '(no title)'))
        block(lines,'ALSO IN tools/',['NAME','ITS TITLE'],extras)
    return '\n'.join(lines).rstrip()+'\n'

def generate(workspaces,system,output,operations=(),as_of=None):
    if operations:raise ValueError('Overlay the proposal on a copy before generation.')
    day=as_of or date.today().isoformat();made=[]
    for ws in sorted(workspaces.iterdir()):
        if not ws.is_dir() or ws.is_symlink() or not safe(ws.name) or not (ws/'AGENTS.md').is_file():continue
        for section in ('TEAM','SKILLS','TOOLS'):
            p=output/ws.name/(section+'.md');p.parent.mkdir(parents=True,exist_ok=True);body=render(ws,section,system,day)
            if not p.exists() or p.read_text(encoding='utf-8')!=body:
                with p.open('w', encoding='utf-8', newline='\n') as stream:
                    stream.write(body)
            made.append(p)
    return made

def main():
    inferred=Path(__file__).resolve().parent.parent
    default_home=inferred if inferred.name in ('.foxrun','.foxrun') else Path.home()/'.foxrun'
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--system-home',type=Path,default=default_home);p.add_argument('--workspace-root',type=Path)
    p.add_argument('--output-root',type=Path);p.add_argument('--as-of');p.add_argument('--check',action='store_true');a=p.parse_args();bad=[]
    if a.workspace_root is None:a.workspace_root=a.system_home.parent/a.system_home.name.lstrip('.')
    if a.check:
        for ws in sorted(a.workspace_root.iterdir()):
            if ws.is_dir() and not ws.is_symlink() and (ws/'AGENTS.md').is_file():
                for section in ('TEAM','SKILLS','TOOLS'):
                    target=a.system_home/'workspaces'/ws.name/(section+'.md')
                    if not target.is_file() or target.read_text(encoding='utf-8')!=render(ws,section,a.system_home,a.as_of or date.today().isoformat()):bad.append(str(target))
        print(json.dumps({'stale':bad}));return int(bool(bad))
    made=generate(a.workspace_root,a.system_home,a.output_root or a.system_home/'workspaces',as_of=a.as_of);print('%d pages for %d workspaces'%(len(made),len(made)//3));return 0

if __name__=='__main__':raise SystemExit(main())
