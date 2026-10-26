#!/usr/bin/env python3
"""Render the approved capabilities form from seat declarations and source pages."""
import os
import json
from datetime import date
from pathlib import Path
import re
from page_indexes import cell
from make_workspaces_view import parse, seat_fields, sentence, tool_inventory, tool_dependencies, tool_scopes, tool_visible, shelf, KINDS, MARKS

HOW='**How to read a row.** A tool row says what the tool is. A skill row says what the skill does, and the tools it needs. A skill does not work when a tool it needs is not set up. Each name opens its own page.'

def anchor(text):return '#'+re.sub(r'[^\w -]','',text.lower()).replace(' ','-')
def link(path,page,name):
    from urllib.parse import quote
    return '[%s](%s)'%(cell(name),quote(os.path.relpath(str(path),str(page.parent)),safe='/.-_'))

def capabilities(ws,SYS,WS,**unused):
    home=WS/ws;page=home/'tools/CAPABILITIES.md';known=tool_inventory(home,SYS)
    loaded_tools=set();loaded_skills=set()
    for seat in sorted((home/'team').glob('*.md')):
        if seat.name=='TEAM.md' or seat.is_symlink():continue
        fields=seat_fields(seat,SYS)
        for key,target in [('skills',loaded_skills),('tools' if 'id' in fields else 'mcpServers',loaded_tools)]:
            if isinstance(fields.get(key),list):target.update(fields[key])
    own_tools={name for name,(path,_,_,_) in known.items() if home/'tools' in path.parents}
    own_skills={p.parent.name:p for p in (home/'skills').glob('*/SKILL.md') if not p.is_symlink()}
    publication=json.loads((SYS/'config/catalog.yaml').read_text()).get('where',{})
    all_skills={}
    for root in (SYS/'skillwright/skills',SYS/'skills',home/'skills'):
        for path in root.glob('*/SKILL.md'):
            if root!=home/'skills' and publication.get(path.parent.name)=='off':continue
            if not path.is_symlink():all_skills[path.parent.name]=path
    names=set(own_skills)|loaded_skills;named=set()
    pattern=re.compile(r'(?<![\w-])'+re.escape(ws)+r'(?![\w-])',re.I)
    for name,path in all_skills.items():
        if home/'skills' not in path.parents and pattern.search(name+' '+path.read_text()):names.add(name);named.add(name)
    scopes=tool_scopes(SYS)
    excluded={name for (kind,name) in scopes if name not in known and not tool_visible(name,kind,scopes,ws)}
    excluded.update(set(tool_inventory(home,SYS,include_excluded=True))-set(known))
    selected=own_tools|loaded_tools|{row['name'] for row in shelf(home,SYS)}
    for name,(path,fields,body,title) in known.items():
        if pattern.search(name+' '+body):selected.add(name)
    gaps={'Tools with no use':[],'Skills with no use':[],'Tools with no page':[],'Tool pages not on the template':[],
        'Skills a seat loads, not on disk':[],'Pages in tools/ that are not a tool page':[]}
    tools={};skills={}
    for name in sorted(selected):
        if name in excluded:continue
        item=known.get(name)
        if not item:gaps['Tools with no page'].append(name);tools[name]=('',[cell(name),'(unknown)','(a tool with no page yet)']);continue
        path,fields,body,title=item;use=fields.get('use','');good=all(fields.get(k) for k in ('name','what','kind','use','status'))
        if not use:gaps['Tools with no use'].append(name)
        if not good:gaps['Tool pages not on the template'].append(name)
        tools[name]=(use,[MARKS.get(fields.get('status'),'')+' '+link(path,page,title),path.parent.name,cell(sentence(fields.get('what') or fields.get('description') or '(not on the page)'))])
    for name in sorted(names):
        path=all_skills.get(name)
        if not path:
            gap='Skills excluded by catalog' if publication.get(name)=='off' else 'Skills a seat loads, not on disk'
            gaps.setdefault(gap,[]).append(name);continue
        fields,body,title=parse(path);use=fields.get('use') or (fields.get('metadata',{}).get('category','') if isinstance(fields.get('metadata'),dict) else '')
        if not use:gaps['Skills with no use'].append(name)
        needs,missing,has_tools=tool_dependencies(path,known,page,excluded)
        skills[name]=(use,[link(path,page,'`'+name+'`'),cell(sentence(fields.get('description') or '(not on disk)')),needs])
    for kind in KINDS:
        for path in (home/'tools'/kind).glob('*.md'):
            if path.is_symlink():continue
            if parse(path)[0].get('type')!='tool':gaps['Pages in tools/ that are not a tool page'].append(kind+'/'+path.name)
    for path in sorted((home/'tools').glob('*.md')):
        if path.name!='CAPABILITIES.md' and not path.is_symlink():
            gaps['Pages in tools/ that are not a tool page'].append(path.name)
    uses=sorted(set(u[:1].upper()+u[1:] for u,_ in list(tools.values())+list(skills.values()) if u),key=str.lower)
    # Keep every in-scope row visible. A missing use gets a counted gap and a table under Not placed yet.
    day=os.environ.get('FOXRUN_PAGE_AS_OF',date.today().isoformat())
    lines=['<!-- Built by workspace_pages.py. Do not edit. -->','---','type: index','workspace: '+ws,'timestamp: '+day+'T00:00:00Z','---','# Capabilities: '+ws,'',
        'Every tool and skill this workspace uses, by use. A script makes this page.',
        'Edit a tool page, a skill, or a seat file; then run the script.','', '## Contents','', '- **By use**']
    for use in uses:
        count_t=sum(u.casefold()==use.casefold() for u,_ in tools.values());count_s=sum(u.casefold()==use.casefold() for u,_ in skills.values())
        lines += ['  - [%s](%s) · %d tools · %d skills'%(cell(use),anchor(use),count_t,count_s)]
    lines += ['- **Not placed yet**','  - [Not placed yet](#not-placed-yet)']
    for title,names_ in gaps.items():
        if names_:lines += ['  - [%s](%s) · %d'%(title,anchor(title),len(names_))]
    lines += ['', '```','USES    '+str(len(uses)), 'TOOLS   %d  with a use: %d'%(len(tools),sum(bool(u) for u,_ in tools.values())),
        'SKILLS  %d  with a use: %d'%(len(skills),sum(bool(u) for u,_ in skills.values())),'MADE    '+day+' 00:00','```','',HOW,'']
    def rows_for(use):
        for columns,data in [(['Tool','Kind','What it is'],tools),(['Skill','What it does','Tools it needs'],skills)]:
            rows=[row for u,row in data.values() if u.casefold()==use.casefold()]
            if rows:lines.extend(['| '+' | '.join(columns)+' |','|'+'|'.join('---' for _ in columns)+'|']+['| '+' | '.join(row)+' |' for row in rows]+[''])
    for use in uses:lines.extend(['## '+use,'']);rows_for(use)
    lines += ['## Not placed yet','','Each name here is in use and has a gap. Give it a use, a page, or a folder.','']
    rows_for('')
    for title,names_ in gaps.items():
        if not names_:continue
        lines += ['### '+title,'','```','NAMES  (%d)'%len(names_)]
        current='   '
        for name in sorted(names_):
            if len(current+name)>78:lines.append(current.rstrip());current='   '
            current+=name+'  '
        if current.strip():lines.append(current.rstrip())
        lines += ['```','']
    lines += ['%d skills are here because their name or their line names this workspace.'%len(named)]
    from module_commands import render as module_section
    lines += ['', module_section(SYS,home).rstrip()]
    return '\n'.join(lines)+'\n',{'tools':len(tools),'skills':len(skills),'uses':len(uses),'pages':len(known)}
