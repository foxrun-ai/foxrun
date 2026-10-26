#!/usr/bin/env python3
"""One failing gate for proposed writes, commits, releases, and agent tool events."""
import argparse
import ast
from contextlib import contextmanager, nullcontext
import io
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys
from unittest.mock import patch
from urllib.parse import quote, unquote, urlsplit
from lint import Lint, Page, POLICY, protected, inside, path_match
from base.paths import resolve_portfolio_path, APP_FOLDERS

ROOT=Path(__file__).resolve().parents[1]

def commit_guard(home, portfolio, policy=POLICY, runner=subprocess.run):
    """Refuse partial staging so the lint cannot inspect different bytes than Git commits."""
    clean=runner(['git','diff','--quiet','--'],capture_output=True)
    if clean.returncode:
        raise ValueError('Commit requires a Git worktree with no unstaged tracked changes.')
    listed=runner(['git','ls-files','--others','--exclude-standard','-z'],capture_output=True,text=True)
    if listed.returncode:raise ValueError('Cannot inspect the commit file list.')
    checker=Lint(home,portfolio,policy)
    for name in listed.stdout.split('\0'):
        if not name:continue
        path=Path(os.path.abspath(name))
        if protected(path):raise ValueError('Untracked protected file blocks the commit.')
        if not any(inside(path,root) for root in (checker.home,checker.workspaces)):
            raise ValueError('Commit repository requires an explicit managed-home binding.')
        if any(checker.matches(path,r['scope']) for r in checker.rules):
            raise ValueError('Add or remove untracked managed files before committing.')

def tool_metadata(checker, bases):
    """List immediate tool entries and declared local runtimes; never walk payloads."""
    if not any(rule['kind']=='tool_inventory' for rule in checker.rules):
        return set()
    roots=checker.completion_table('tool-roots',['home','path'])
    declared=checker.completion_table('tools',['home','page','runtime','source'])
    paths=set()
    owners=[('system',bases[0])]+[(name,bases[1]/name) for name in sorted(checker.names)]
    for owner,root in owners:
        for row in roots:
            if row['home'] not in (owner,'workspace' if owner!='system' else 'system'):
                continue
            folder=checker.safe_entry(root,row['path'])
            if folder.is_dir():
                paths.add(folder)
                paths.update(child for child in folder.iterdir() if not protected(child))
        for row in declared:
            if row['home']!=owner:continue
            paths.add(checker.safe_entry(root,row['page']))
            runtime=Path(os.path.expanduser(row['runtime']))
            if not runtime.is_absolute():runtime=checker.safe_entry(root,row['runtime'])
            if any(inside(runtime,base) for base in bases) and not protected(runtime):
                paths.add(runtime)
    return paths

def policy_files(policy):
    """List the complete safe policy without following links or opening protected files."""
    policy=Path(policy).absolute()
    if protected(policy) or protected(policy.resolve()) or policy.is_symlink() or not policy.is_dir():
        raise ValueError('Policy folder is absent, protected, or linked.')
    for current,dirs,files in os.walk(policy,followlinks=False,onerror=lambda e: (_ for _ in ()).throw(e)):
        folder=Path(current)
        kept=[]
        for name in sorted(dirs+files):
            path=folder/name
            if protected(path):continue
            if path.is_symlink():raise ValueError('Linked policy entry: '+str(path))
            if name in dirs:
                kept.append(name)
            elif not path.is_file():raise ValueError('Unsupported policy entry: '+str(path))
        dirs[:]=kept
    return policy

def finding_delta(candidate, baseline):
    """Lines can move during an edit; only a new rule/path/message blocks it."""
    def key(row):return row['rule_id'],row['path'],row['what']
    old={key(row) for row in baseline}
    return [row for row in candidate if key(row) not in old]

# T692: a write check never walks these bulk folders, whatever the policy says.
BULK = frozenset({'archive', 'raw', 'backups', 'runs', 'releases', '.git', 'node_modules'})

class WriteLint(Lint):
    """File writes affect their bytes and ancestor entries, not unrelated pages.

    pages: pages that link to the target (their links are checked in both states).
    pool: Markdown pages a wiki name can resolve to; listed, never opened.
    """
    def __init__(self,home,portfolio,policy,target,pages=(),pool=(),membership=None):
        super().__init__(home,portfolio,policy)
        self.target=target;self.pages=list(pages);self.pool=list(pool)
        self.membership=membership
        # A body write does not change the Git index. Database bytes matter only
        # for database and STATE writes. Other aggregate checks read exact inputs.
        roots=[self.home,self.workspaces,self.workspaces/'atlas']+[self.workspaces/n for n in self.names]
        def affected(rule):
            kind=rule['kind']
            if kind=='tracked_cache':return membership is not None
            if kind=='database':return membership is not None or self.target.suffix=='.db'
            if kind=='required_pages':
                if membership is not None:return True
                return any(self.target==root/row['path'] for root in roots for row in self.data['required-pages'])
            if kind=='tool_inventory':
                if membership is not None:return True
                entries=tool_metadata(self,[self.home,self.workspaces])
                owners=[('system',self.home)]+[(name,self.workspaces/name) for name in self.names]
                for owner,root in owners:
                    for row in self.completion_table('tool-roots',['home','path']):
                        if row['home'] not in (owner,'workspace' if owner!='system' else 'system'):continue
                        folder=root/row['path']
                        if inside(self.target,folder) and not folder.exists():return True
                # A new immediate payload or folder is not in the old listing yet.
                return self.target in entries or any(p.parent in entries and
                    (p==self.target or not p.exists()) for p in [self.target,*self.target.parents])
            if kind=='lint_growth':
                return self.target in {self.home/'base/lint_rule.py',self.home/'skillwright/skills/lint-rule/SKILL.md'}
            if kind=='lint_gates':
                return any(self.target==self.home/row['path'] for row in self.completion_table('gates',['stage','path','required_text']))
            return True
        self.rules=[r for r in self.rules if affected(r)]
    def rule_roots(self):
        if self.membership is None:return super().rule_roots()
        # The portfolio sees the new entry; only the new workspace gains rules.
        return [('portfolio',self.workspaces)]+([('workspace',self.membership)]
            if self.membership.name in self.names else [])
    def repository_roots(self):
        if self.membership is None:return super().repository_roots()
        return [self.membership] if self.membership.name in self.names else []
    def required_pages(self, rule):
        if self.membership is not None:return super().required_pages(rule)
        # Only the required page being changed can gain a new finding.
        data = self.data['required-pages']
        self.data['required-pages'] = [row for row in data if any(
            self.target == root / row['path'] for root in
            [self.home, self.workspaces, self.workspaces / 'atlas'] +
            [self.workspaces / name for name in self.names])]
        try:super().required_pages(rule)
        finally:self.data['required-pages'] = data
    def inventory(self,selected=None):
        for root in (self.home,self.workspaces):
            if protected(root) or root.is_symlink() or not root.is_dir():
                raise ValueError('Home is absent, protected, or linked: '+str(root))
        if self.membership is not None:
            # Membership can change checks of existing pages in this workspace.
            # Use the engine's pruning and the same virtual-entry handling.
            self.inventory_roots=[self.membership] if os.path.isdir(self.membership) else []
            self.draft_target=self.target;self.new_target=True
            Lint.inventory(self,selected)
            DraftLint.draft_entries(self,selected)
        else:
            self.files=[self.target] if self.target.is_file() else []
        self.files=list(dict.fromkeys(self.files+[p for p in self.pages if p!=self.target and p.is_file()]))
        self.dirs=list(dict.fromkeys(self.dirs+[p for p in self.target.parents if p.is_dir()
                   and any(inside(p,root) for root in (self.home,self.workspaces))]))
    def wiki_pages(self):
        # Only wiki names used by the checked pages need an index. Keep all
        # matching candidates, so ambiguity and section checks stay identical.
        names=set()
        for path in self.files:
            if path.suffix.lower()!='.md':continue
            text='\n'.join(self.page(path).visible)
            for ref in re.findall(r'\[\[([^\]\n]+)\]\]',text):
                name=unquote(ref.split('|',1)[0].split('#',1)[0])
                if name and not name.startswith(('~','/','.')):
                    names.add(name if Path(name).suffix else name+'.md')
        return list(dict.fromkeys(self.files+[p for p in self.pool
            if any(p.as_posix().endswith('/'+name) for name in names)]))
    def run(self,*args,**kwargs):
        return super().run(*args,**kwargs) if self.rules else []

def fast_link_pool(checker,rules,query=None):
    """Optional native filename listing; the engine still applies every scope.

    rg is only an accelerator. The standard-library walk remains the fallback.
    No file bytes are requested, and rg never follows links.
    """
    executable=shutil.which('rg')
    if not executable:return None
    names={*BULK,*checker.excluded}
    # Prune only exclusions shared by every links rule, independent of home.
    common=None
    for rule in rules:
        patterns={term[3:].rstrip('/') for term in rule['scope'].split(';')
                  if term.startswith('!*:') and term.endswith('/')}
        common=patterns if common is None else common & patterns
    globs=['!'+p+'/**' for p in sorted(common or ())]
    globs+=['!**/'+name+'/**' for name in sorted(names)]
    pool=[]
    folders=[(name,str(folder)+'/') for name,folder in checker.workspace_folders()]
    contexts=checker.__dict__.setdefault('_contexts',{})
    names_key=tuple(sorted(checker.names))
    for root in (checker.home,checker.workspaces):
        command=[executable]+(['--files'] if query is None else ['--files-with-matches','--text','--regexp',query])
        command+=['--hidden','--no-ignore','--null','--glob','*.[mM][dD]']
        for pattern in globs:command+=['--glob',pattern]
        if root==checker.workspaces:
            for name in sorted(APP_FOLDERS):command+=['--glob','!'+name+'/**']
        label='system/' if root==checker.home else 'portfolio/'
        for entry in checker.excluded_paths:
            if entry.startswith(label):command+=['--glob','!'+entry[len(label):]+'/**']
        # Home-specific exclusions need their actual portfolio prefix.
        groups=[('system','')] if root==checker.home else [('workspace',name+'/') for name in checker.names]+([('atlas','atlas/')] if 'atlas' not in checker.names else [])
        for group,prefix in groups:
            shared=None
            for rule in rules:
                patterns={term.split(':',1)[1].rstrip('/') for term in rule['scope'].split(';')
                          if term.startswith('!'+group+':') and term.endswith('/')}
                shared=patterns if shared is None else shared & patterns
            for pattern in sorted(shared or ()):command+=['--glob','!'+prefix+pattern+'/**']
        done=subprocess.run(command+['.'],cwd=root,capture_output=True,text=True)
        if done.returncode not in (0,1):return None
        for name in filter(None,done.stdout.split('\0')):
            if name.startswith('./'):name=name[2:]
            path=root/name
            if protected(path) or path.is_symlink():continue
            # rg does not follow links. Its listed paths have plain ancestors,
            # so the resolved workspace prefixes give the engine's context.
            if root==checker.home:
                parts=name.split('/')
                context=('system',name,parts[1] if len(parts)>=3 and parts[0]=='workspaces' else 'system')
            else:
                text=str(path)
                context=next((('workspace',text[len(prefix):],owner)
                    for owner,prefix in folders if text.startswith(prefix)),None)
                if context is None:
                    first,sep,tail=name.partition('/')
                    context=('atlas',tail,'atlas') if sep and first=='atlas' else ('portfolio',name,'portfolio')
            contexts[(str(path),names_key)]=context
            if any(checker.matches(path,r['scope']) for r in rules):pool.append(path)
    return pool


def link_pool(checker):
    """List only link-policy Markdown entries, without resolving each walked ancestor."""
    rules=[r for r in checker.rules if r['kind']=='links']
    pool=[]
    if not rules:return pool
    accelerated=fast_link_pool(checker,rules)
    if accelerated is not None:return accelerated
    exclusions={}
    for home in ('system','workspace','portfolio','atlas'):
        selections=[]
        for rule in rules:
            folders,paths=checker.negative_terms(rule['scope'],home)
            names={p[3:] for p in folders if p.startswith('**/') and not any(c in p[3:] for c in '*?[') and '/' not in p[3:]}
            exact={p for p in folders if not any(c in p for c in '*?[')}
            other=set(folders)-exact-{'**/'+name for name in names}
            selections.append((names,exact,other,paths))
        exclusions[home]=selections
    names_key=tuple(sorted(checker.names))
    def context(root,relative):
        if root==checker.home:
            parts=relative.split('/')
            return 'system',relative,parts[1] if len(parts)>=3 and parts[0]=='workspaces' else 'system'
        name,sep,tail=relative.partition('/')
        return (('workspace',tail,name) if sep and name in checker.names else
                ('atlas',tail,'atlas') if sep and name=='atlas' else ('portfolio',relative,'portfolio'))
    for root in (checker.home,checker.workspaces):
        prefix=str(root)+'/'
        label='system/' if root==checker.home else 'portfolio/'
        for current,dirs,files in os.walk(root,followlinks=False):
            parent=current[len(prefix):]+'/' if current!=str(root) else ''
            kept=[]
            for name in dirs:
                relative=parent+name
                home,rel,_=context(root,relative)
                if root==checker.workspaces and not parent and name in APP_FOLDERS:continue
                if name in BULK or name in checker.excluded:continue
                # Since parents were pruned, only this directory can start an exclusion.
                if all(name in common or rel in exact or any(path_match(rel,p) for p in other+tuple(paths))
                       for common,exact,other,paths in
                       [(a,b,tuple(c),d) for a,b,c,d in exclusions[home]]):continue
                child=Path(current)/name
                if protected(child) or child.is_symlink():continue
                if label+relative in checker.excluded_paths:continue
                kept.append(name)
            dirs[:]=kept
            for name in files:
                if os.path.splitext(name)[1].lower()!='.md':continue
                path=Path(current)/name
                if protected(path) or path.is_symlink():continue
                checker.__dict__.setdefault('_contexts',{})[(str(path),names_key)]=context(root,parent+name)
                if any(checker.matches(path,r['scope']) for r in rules):pool.append(path)
    return pool

def link_referrers(checker,target,pool,new):
    """Pages whose links reach any target, with one search over the pool.

    For a page that exists, only links with a section matter (changed headings).
    """
    targets={target} if isinstance(target,Path) else set(target)
    if not targets:return []
    rules=[r for r in checker.rules if r['kind']=='links']
    names={p.name for p in targets};stems_set={p.stem for p in targets}
    target_names=(names,stems_set)
    def either(text):return {text,quote(text)}
    files='|'.join(re.escape(n) for n in sorted({n for p in targets for n in either(p.name)}))
    stems='|'.join(re.escape(n) for n in sorted({n for p in targets for n in either(p.stem)}))
    # A fast byte search finds every page that could hold such a link; the
    # engine's own parsing then decides.
    if new:words='(?:'+files+')|\\[\\[[^\\]\\n]*(?:'+stems+')'
    else:words='(?:'+files+')#|\\[\\[[^\\]\\n]*(?:'+stems+')[^\\]\\n]*#'
    pattern=re.compile(words.encode())
    tails=set()
    for target in targets:
        parts=checker.context(target)[1].split('/')
        tails.update('/'.join(parts[i:]) for i in range(len(parts)))
    def hits(ref):
        name,fragment,wiki,candidates=ref
        if not new and not fragment:return False
        suffix=name if Path(name).suffix else name+'.md'
        if wiki and name and not name.startswith(('~','/','.')) and suffix in tails:return True
        for candidate in candidates:
            try:
                if candidate in targets or (inside(candidate,checker.workspaces)
                        and resolve_portfolio_path(candidate,checker.workspaces) in targets):return True
            except ValueError:continue
        return False
    found=[]
    accelerated=fast_link_pool(checker,rules,pattern.pattern.decode())
    candidates=set(accelerated) if accelerated is not None else None
    for page in pool:
        if page in targets or candidates is not None and page not in candidates:continue
        try:
            with open(page,'rb') as stream:raw=stream.read()
        except OSError:continue  # The full nightly lint reports unreadable pages.
        if not pattern.search(raw):continue
        selected=[r for r in rules if checker.matches(page,r['scope'])]
        # Resolve matching literals before constructing a Page. An unrelated
        # contract mention must not parse and retain a large document.
        if not any(hits(ref) for ref in page_refs(checker,page,raw.decode('utf-8',errors='replace'),selected,target_names)):continue
        try:text='\n'.join(checker.page(page).visible)
        except (OSError,UnicodeError,ValueError):continue
        if any(hits(ref) for ref in page_refs(checker,page,text,selected,target_names)):found.append(page)
    return found

def wiki_index(checker,scope):
    """The engine's wiki-name index over checker.wiki_pages(), for one links scope."""
    indexes=checker.__dict__.setdefault('_gate_wiki',{})
    if scope not in indexes:
        index={}
        for p in checker.wiki_pages():
            if p.suffix.lower()!='.md' or not checker.matches(p,scope):continue
            parts=checker.context(p)[1].split('/')
            for i in range(len(parts)):index.setdefault('/'.join(parts[i:]),[]).append(p)
        indexes[scope]=index
    return indexes[scope]

def page_refs(checker,page,text,selected,target_names=None):
    """Yield (name, fragment, wiki, candidates) for each local link, as the engine reads them."""
    text=re.sub(r'(`+)([^`]*?)\1',lambda m:re.sub(r'[^\n]',' ',m.group()),text)
    refs=[(m.group(1),False) for m in re.finditer(r'!?\[[^\]\n]*\]\(\s*(<[^>]+>|[^\s)]+)',text)]
    refs.extend((m.group(1).split('|',1)[0],True) for m in re.finditer(r'\[\[([^\]\n]+)\]\]',text))
    refs.extend((m.group(1),False) for m in re.finditer(r'(?m)^\s*\[(?!\^)[^\]\n]+\]:\s*(<[^>]+>|[^\s\[\]]+)',text))
    for literal,wiki in refs:
        literal=literal.strip('<>')
        coordinate=re.fullmatch(r'(.+\.[A-Za-z0-9]+):[1-9]\d*(?::[1-9]\d*)?',literal)
        if coordinate:literal=coordinate.group(1)
        if re.match(r'^[A-Za-z][\w+.-]*:',literal) or literal.startswith('//') or any(c in literal for c in ('{','}','*','$','\\')):continue
        try:parsed=urlsplit(literal)
        except ValueError:continue
        name,fragment=unquote(parsed.path),unquote(parsed.fragment)
        if target_names is not None and Path(name).name not in target_names[0] and (not wiki or Path(name).name not in target_names[1]):continue
        if name.startswith('~/.foxrun'):path=checker.home/name[len('~/.foxrun'):].lstrip('/')
        elif name.startswith('~/foxrun'):path=checker.workspaces/name[len('~/foxrun'):].lstrip('/')
        elif name.startswith(('~','/')):path=Path(os.path.expanduser(name))
        else:path=page.parent/name if name else page
        path=Path(os.path.abspath(str(path)))
        candidates=[path,path.with_suffix('.md')] if wiki and not path.suffix else [path]
        if wiki and name and not name.startswith(('~','/')):
            home,_,owner=checker.context(page)
            roots=([checker.workspaces/owner] if home in ('workspace','atlas') else [])+[checker.home,checker.workspaces]
            for root in roots:
                candidate=Path(os.path.abspath(str(root/name)))
                candidates.extend([candidate,candidate.with_suffix('.md')] if not candidate.suffix else [candidate])
        if wiki and name and not name.startswith(('~','/','.')) and not any(c.exists() for c in candidates):
            # The engine falls back to the wiki index; keep those pages too (T692).
            suffix=name if Path(name).suffix else name+'.md'
            for r in selected:
                candidates.extend(wiki_index(checker,r['scope']).get(suffix,[]))
        yield name,fragment,wiki,candidates

def needs_home_scan(checker,target,body):
    # Policy, database, renderer, and screenshot changes can affect other pages.
    if inside(target,checker.policy) or '.git' in target.parts or target.suffix=='.db':return True
    if target==checker.home/'base/lint_render.py':return True
    if any(r['kind']=='brand_page' for r in checker.rules):
        rows=checker.completion_table('visual-reviews',['home','page','source_sha256','renderer_sha256',
            'width','overflow','status','reviewer','image','image_sha256'])
        if any(target==checker.home/r['image'] for r in rows):return True
    return False

def link_neighbors(checker,target,body):
    """T692: what a page write needs beyond its own bytes, without a home scan.

    A new page or changed headings can change incoming links (ambiguity,
    anchors): check the pages that name the target. A wiki link can resolve
    by name: list the pool of pages. Otherwise the page stands alone.
    Returns (referrers, pool).
    """
    if target.suffix.lower()!='.md' or not any(r['kind']=='links' and checker.matches(target,r['scope'])
                                              for r in checker.rules):return [],[]
    new=Page(body)
    old=checker.page(target) if target.is_file() else None
    incoming=old is None or ([(depth,title) for depth,title,_ in old.headings]!=
                             [(depth,title) for depth,title,_ in new.headings])
    wiki=any('[[' in '\n'.join(page.visible) for page in (old,new) if page is not None)
    if not incoming and not wiki:return [],[]
    pool=link_pool(checker)
    return (link_referrers(checker,target,pool,old is None) if incoming else []),pool

@contextmanager
def draft_overlay(target,body):
    """Present one draft path to lint while every other path stays on disk."""
    target=Path(target)
    original_open=Path.open
    original_exists=Path.exists
    original_is_file=Path.is_file
    original_is_dir=Path.is_dir
    original_iterdir=Path.iterdir
    missing=[]
    parent=target.parent
    while not parent.exists():
        missing.append(parent)
        parent=parent.parent
    virtual_dirs=set(missing)
    virtual={target,*virtual_dirs}

    def open_draft(path,mode='r',buffering=-1,encoding=None,errors=None,newline=None):
        if path==target and mode in ('r','rb'):
            data=io.BytesIO(body.encode('utf-8'))
            return data if mode=='rb' else io.TextIOWrapper(data,encoding=encoding or 'utf-8',errors=errors,newline=newline)
        return original_open(path,mode,buffering,encoding,errors,newline)

    def exists(path,*args,**kwargs):
        return path in virtual or original_exists(path,*args,**kwargs)

    def is_file(path,*args,**kwargs):
        return path==target or original_is_file(path,*args,**kwargs)

    def is_dir(path,*args,**kwargs):
        return path in virtual_dirs or original_is_dir(path,*args,**kwargs)

    def iterdir(path):
        children=list(original_iterdir(path)) if original_is_dir(path) else []
        child=next((entry for entry in virtual if entry.parent==path),None)
        if child is not None and child not in children:children.append(child)
        return iter(children)

    with patch.object(Path,'open',open_draft),patch.object(Path,'exists',exists),\
         patch.object(Path,'is_file',is_file),patch.object(Path,'is_dir',is_dir),\
         patch.object(Path,'iterdir',iterdir):
        yield

class DraftLint(Lint):
    """Include an absent draft path in a full scan without writing it."""
    def __init__(self,home,portfolio,policy,target,new_target):
        super().__init__(home,portfolio,policy)
        self.draft_target=target
        self.new_target=new_target

    def inventory(self,selected=None):
        super().inventory(selected)
        self.draft_entries(selected)

    def draft_entries(self,selected=None):
        target=self.draft_target
        rules=self.rules if selected is None else selected
        rules=[rule for rule in rules if rule['kind'] not in
               ('allowed_top','required_pages','database','tracked_cache','tool_inventory','lint_growth','lint_gates')]
        owner=next((root for root in (self.home,self.workspaces) if inside(target,root)),None)
        if owner is None or not rules or protected(target) or self.skipped_workspace(target):return
        parents=[]
        for parent in target.parents:
            if parent==owner:break
            parents.append(parent)
        # Match the ordinary walk's pruning before adding virtual entries.
        for parent in reversed(parents):
            label='system/' if owner==self.home else 'portfolio/'
            if (protected(parent) or parent.is_symlink() or parent.name in self.excluded
                    or label+parent.relative_to(owner).as_posix() in self.excluded_paths
                    or all(self.excluded_by_scope(parent,rule['scope']) for rule in rules)):
                return
        if (self.new_target and target.is_file() and not target.is_symlink() and target not in self.files
                and target.name not in {'.DS_Store','.gitkeep'}
                and any(self.matches(target,rule['scope']) for rule in rules)):
            self.files.append(target)
        for parent in reversed(parents):
            if parent.is_dir() and parent not in self.dirs:self.dirs.append(parent)

def evaluate(home, portfolio, target=None, body=None, policy=POLICY):
    if target is not None:policy=policy_files(policy)
    checker=Lint(home,portfolio,policy)
    if target is None:
        return checker.run()
    target=Path(os.path.abspath(str(target)))
    if inside(target, checker.workspaces):
        target=resolve_portfolio_path(target, checker.workspaces)
    bases=[checker.home,checker.workspaces]
    if any(inside(bases[i],bases[1-i]) for i in range(2)):
        raise ValueError('Managed homes must be separate folders.')
    owner=next((p for p in bases if inside(target,p)),None)
    if owner is None or protected(target) or target==owner:
        raise ValueError('Write target is outside the managed homes or protected.')
    cursor=target
    while cursor!=owner:
        if cursor.is_symlink():raise ValueError('Writes cannot traverse links.')
        cursor=cursor.parent
    if target.exists() and not target.is_file():raise ValueError('Write target must be a regular file or an absent file path.')
    if body is None:raise ValueError('A proposed body is required before writing.')
    if target.suffix=='.py':ast.parse(body,feature_version=(3,9))
    # App repositories and independent layouts never acquire workspace rules.
    if checker.skipped_workspace(target):return []
    # A valid target outside every rule's scope has no page checks to run.
    if not any(checker.matches(target,r['scope']) for r in checker.rules):return []
    scoped=not needs_home_scan(checker,target,body)
    new_target=not target.is_file()
    membership=target.parent if (new_target and target.name=='AGENTS.md'
        and target.parent.parent==checker.workspaces and not target.parent.name.startswith('.')) else None
    # T692: a page write checks the page and the few pages its links need.
    referrers,pool=link_neighbors(checker,target,body) if scoped and membership is None else ([],[])
    if scoped and membership is not None:
        pool=link_pool(checker)
        # Membership changes scope and wiki-name visibility. Include referrers
        # to every page whose indexed name or inclusion can change.
        with draft_overlay(target,body):
            registered=Lint(bases[0],bases[1],policy)
            registered.inventory_roots=[membership] if os.path.isdir(membership) else []
            registered.inventory([r for r in registered.rules if r['kind']=='links'])
            pool=list(dict.fromkeys(pool+[p for p in registered.files if p.suffix.lower()=='.md']))
            affected=[target]+[p for p in pool if inside(p,membership)]
            # Search all affected names together; read each candidate only once.
            referrers+=link_referrers(registered,affected,pool,True)
        referrers=list(dict.fromkeys(referrers))
    def scan(candidate):
        with draft_overlay(target,body) if candidate else nullcontext():
            runner=(WriteLint(bases[0],bases[1],policy,target,referrers,pool,membership)
                    if scoped else DraftLint(bases[0],bases[1],policy,target,new_target))
            runner._contexts=checker.__dict__.setdefault('_contexts',{})
            return runner.run()
    baseline=scan(False)
    return finding_delta(scan(True),baseline)

def hook(event,home,portfolio,policy=POLICY):
    if not isinstance(event,dict) or not isinstance(event.get('tool_input',{}),dict):
        raise ValueError('Hook event and tool_input must be objects.')
    name=event.get('tool_name');data=event.get('tool_input',{})
    if name=='Bash':
        command=data.get('command','')
        if any(x in command for x in ('\n',';','|','>','<','`','$(','&&')):raise ValueError('Use the managed write gate for shell changes.')
        words=shlex.split(command)
        if words and words[0] in ('pwd','ls') and not any(protected(word) for word in words[1:]):
            return []
        raise ValueError('Shell mutations require the managed write gate; unclassified commands stop.')
    if name not in ('Write','Edit'):raise ValueError('Unsupported write event.')
    target=Path(os.path.abspath(data['file_path']))
    if inside(target, Path(portfolio).absolute()):
        target=resolve_portfolio_path(target, portfolio)
    if protected(target):raise ValueError('Protected write target.')
    if name=='Write':body=data['content']
    else:
        if not any(inside(target.absolute(),Path(p).absolute()) for p in (home,portfolio)) or target.is_symlink():raise ValueError('Edit outside managed homes.')
        cursor=target.parent
        while cursor not in (Path(home).absolute(),Path(portfolio).absolute()):
            if cursor.is_symlink() or cursor==cursor.parent:raise ValueError('Unsafe edit path.')
            cursor=cursor.parent
        body=target.read_text();old=data['old_string']
        if not old or old not in body or body.count(old)!=1 and not data.get('replace_all'):raise ValueError('Edit text does not match uniquely.')
        body=body.replace(old,data['new_string'],-1 if data.get('replace_all') else 1)
    return evaluate(home,portfolio,target,body,policy)

SECRET_PATTERNS=(re.compile(r'-----BEGIN [A-Z ]*PRIVATE KEY-----'),re.compile(r'\b(?:AKIA|ASIA)[0-9A-Z]{16}\b'),re.compile(r'(?i)aws_secret_access_key\s*[=:]\s*\S{40}'),
    re.compile(r'\bgh[pousr]_[A-Za-z0-9]{36}\b'),re.compile(r'\bgithub_pat_[A-Za-z0-9_]{40,}\b'),
    re.compile(r'\bxox[abprs]-[A-Za-z0-9-]{10,}'),re.compile(r'\bxapp-[A-Za-z0-9-]{10,}'),re.compile(r'\bsk-(?:ant-|proj-)?[A-Za-z0-9_-]{20,}'))

def secret_reason(event):
    """g-checks-never-block-work-except-secrets: the only save-time blocks are security:
    secret paths (raw and resolved, so a link cannot hide one) and secret-looking text."""
    if not isinstance(event,dict):return None
    data=event.get('tool_input') or {}
    if not isinstance(data,dict):return None
    paths=[data.get(k) for k in ('file_path','notebook_path') if data.get(k)]
    command=str(data.get('command',''))
    if command:
        spaced=re.sub(r'(>>?|<|\|)',r' \1 ',command)  # catch echo x >>.env
        try:words=shlex.split(spaced)
        except ValueError:words=spaced.split()
        paths+=[w for w in words if w not in ('>','>>','<','|')]
    for raw in paths:
        try:candidate=Path(os.path.abspath(os.path.expanduser(str(raw))))
        except (ValueError,TypeError):return 'Unreadable write path.'  # fail closed
        try:resolved=candidate.resolve()
        except (OSError,RuntimeError,ValueError):return 'Unreadable write path: '+str(raw)  # fail closed
        if protected(candidate) or protected(resolved):return 'Protected secret path: '+str(raw)
    texts=[str(data.get(k,'')) for k in ('content','new_string','new_source','command')]
    edits=data.get('edits');edits=edits if isinstance(edits,list) else []
    texts+=[str(e.get('new_string','')) for e in edits if isinstance(e,dict)]
    text=' '.join(texts)
    for pattern in SECRET_PATTERNS:
        if pattern.search(text):return 'This write holds what looks like a secret key or token. Use agent-secret-read and refer to it as [REDACTED].'
    return None

def deny_hook(reason):
    """Claude PreToolUse modern deny schema; exit 0 lets Claude read this decision."""
    print(json.dumps({'hookSpecificOutput': {
        'hookEventName': 'PreToolUse', 'permissionDecision': 'deny',
        'permissionDecisionReason': reason}}))
    return 0

def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--mode',choices=['write','commit','release','hook'],required=True)
    p.add_argument('--home',type=Path,default=Path(os.environ.get('FOXRUN_HOME',str(ROOT))))
    p.add_argument('--workspaces',type=Path,default=Path(os.environ.get('FOXRUN_PORTFOLIO',str(ROOT.parent/('foxrun' if ROOT.name=='.foxrun' else 'foxrun')))))
    p.add_argument('--target',type=Path);p.add_argument('--body',type=Path,
        help='Path to an existing UTF-8 regular file containing the proposed bytes; never inline text.')
    a=p.parse_args(argv)
    try:
        if a.mode=='hook':
            # g-checks-never-block-work-except-secrets: only a secret blocks a save.
            # Page and workspace rules run as warnings (write mode) and hourly.
            try:
                event=json.load(sys.stdin)
                reason=secret_reason(event)
            except Exception as error:  # The secret check fails closed; nothing else blocks.
                return deny_hook('The secret check could not read this tool call: '+str(error))
            return deny_hook('Lint blocked this tool call. '+reason) if reason else 0
        elif a.mode=='write':
            if not a.target or not a.body or protected(a.body) or protected(a.body.resolve()) or a.body.is_symlink() or not a.body.is_file():
                raise ValueError('--body must be a path to an existing safe UTF-8 regular file; inline text is not accepted.')
            findings=evaluate(a.home,a.workspaces,a.target,a.body.read_text(encoding='utf-8'),a.home/'config/lint')
        else:
            if a.mode=='commit':commit_guard(a.home,a.workspaces)
            findings=evaluate(a.home,a.workspaces)
        if a.mode=='hook':
            errors=[r for r in findings if r['level']=='error']
            if errors:
                reason='Lint blocked this tool call. '+ '; '.join(
                    r.get('rule_id','LINT')+': '+r.get('what','Lint failed.')+
                    ' '+r.get('how_to_fix','Repair the proposed body.') for r in errors[:5])
                return deny_hook(reason)
            return 0  # Silent pass-through; never emit a findings array as a hook response.
        print(json.dumps(findings,indent=2))
        if a.mode=='write':return int(any(r.get('write')=='blocking' for r in findings))
        return 1 if any(r['level']=='error' for r in findings) else 0
    except (OSError,ValueError,KeyError,TypeError,SyntaxError) as error:
        if a.mode=='hook':return 0  # A check that cannot run never blocks work.
        if a.mode=='write':
            print('FAIL lint gate could not check this write: '+str(error),file=sys.stderr);return 2
        print('FAIL lint gate: '+str(error),file=sys.stderr);return 2
if __name__=='__main__':sys.exit(main())
