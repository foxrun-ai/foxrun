#!/usr/bin/env python3
"""Small YAML subset: maps, lists, scalars, comments, and flow collections.

No tags, anchors, aliases, directives, or block scalar syntax. Duplicate keys
are errors. The writer emits JSON, which is a YAML-compatible representation.
"""
from __future__ import annotations
import ast
import json
import re
from dataclasses import dataclass
from typing import Any

class YAMLError(ValueError):
    pass

@dataclass
class Mark:
    line: int

@dataclass
class Node:
    value: Any
    start_mark: Mark

class MappingNode(Node):
    pass
class SequenceNode(Node):
    pass
class ScalarNode(Node):
    pass

def _parts(text, separator=','):
    result=[]; start=0; depth=0; quote=None; escape=False
    for index,char in enumerate(text):
        if quote:
            if escape: escape=False
            elif char=='\\' and quote=='"': escape=True
            elif char==quote: quote=None
        elif char in "\"'": quote=char
        elif char in '[{': depth+=1
        elif char in ']}': depth-=1
        elif char==separator and depth==0:
            result.append(text[start:index].strip()); start=index+1
    if quote or depth: raise YAMLError('unclosed quote or collection')
    result.append(text[start:].strip())
    return result

def _comment(text):
    quote=None; escape=False
    for index,char in enumerate(text):
        if quote:
            if escape: escape=False
            elif char=='\\' and quote=='"': escape=True
            elif char==quote: quote=None
        elif char in "\"'" and (index==0 or text[index-1] in ' :,[{'): quote=char
        elif char=='#' and (index==0 or text[index-1].isspace()): return text[:index].rstrip()
    return text.rstrip()

def _pair(text, flow=False):
    quote=None; depth=0; escape=False
    for i,c in enumerate(text):
        if quote:
            if escape: escape=False
            elif c=='\\' and quote=='"': escape=True
            elif c==quote: quote=None
        elif c in "\"'" and (i==0 or text[i-1] in ' :,[{'): quote=c
        elif c in '[{': depth+=1
        elif c in ']}': depth-=1
        elif c==':' and depth==0 and (flow or i+1==len(text) or text[i+1].isspace()):
            return text[:i].strip(),text[i+1:].strip()
    return None

def _scalar(text):
    text=text.strip()
    if not text: return None
    if text.startswith('[') and text.endswith(']'):
        return [] if not text[1:-1].strip() else [_scalar(x) for x in _parts(text[1:-1])]
    if text.startswith('{') and text.endswith('}'):
        result={}
        if not text[1:-1].strip(): return result
        for item in _parts(text[1:-1]):
            pair=_pair(item,True)
            if pair is None: raise YAMLError('flow map entry needs colon')
            k,v=pair; key=_scalar(k)
            if key in result: raise YAMLError('duplicate YAML key '+repr(key))
            result[key]=_scalar(v)
        return result
    if text.startswith('"'):
        try: return json.loads(text)
        except ValueError as exc: raise YAMLError(str(exc))
    if text.startswith("'"):
        if not text.endswith("'"): raise YAMLError('unclosed quote')
        return text[1:-1].replace("''", "'")
    if text.startswith(('!','&','*','|','>')): raise YAMLError('unsupported YAML feature')
    if text.lower() in ('null','~'): return None
    if text.lower() in ('true','false'): return text.lower()=='true'
    if re.fullmatch(r'[-+]?\d+',text): return int(text)
    if re.fullmatch(r'[-+]?\d+\.\d+(?:[eE][-+]?\d+)?',text): return float(text)
    return text

def _unique_pairs(pairs):
    result={}
    for key,value in pairs:
        if key in result: raise YAMLError("duplicate YAML key "+repr(key))
        result[key]=value
    return result

def _parse(source):
    if hasattr(source,'read'): source=source.read()
    source=str(source)
    # JSON documents can span multiple lines.
    try:
        value=json.loads(source,object_pairs_hook=_unique_pairs)
        return value,_node(value,0)
    except YAMLError: raise
    except ValueError:
        if source.lstrip().startswith(("{", "[")) and len(source.strip().splitlines())>1:
            raise YAMLError("invalid JSON-compatible YAML document")
    lines=[]
    for number,raw in enumerate(source.splitlines()):
        if '\t' in raw[:len(raw)-len(raw.lstrip())]: raise YAMLError('tabs in indentation')
        text=_comment(raw.lstrip())
        if not text or text in ('---','...'): continue
        lines.append((len(raw)-len(raw.lstrip()),text,number))
    if not lines: return None,None
    def block(pos,indent):
        is_list=lines[pos][1]=='-' or lines[pos][1].startswith('- ')
        value=[] if is_list else {}; nodes=[]
        while pos<len(lines) and lines[pos][0]==indent:
            _,text,line=lines[pos]
            list_entry=text=='-' or text.startswith('- ')
            if list_entry!=is_list:
                if is_list: break
                raise YAMLError('mixed list and map')
            if is_list:
                rest=text[1:].strip(); pos+=1
                pair=_pair(rest)
                if pair:
                    key,tail=pair; item={}; item_nodes=[]
                    key=_scalar(key)
                    if tail: child=_scalar(tail); child_node=_node(child,line)
                    elif pos<len(lines) and lines[pos][0]>indent+2: child,child_node,pos=block(pos,lines[pos][0])
                    else: child=None; child_node=_node(child,line)
                    item[key]=child; item_nodes.append((ScalarNode(str(key),Mark(line)),child_node))
                    if pos<len(lines) and lines[pos][0]>indent:
                        extra,extra_node,pos=block(pos,lines[pos][0])
                        if not isinstance(extra,dict): raise YAMLError('list map continuation must be map')
                        if set(item)&set(extra): raise YAMLError('duplicate YAML key')
                        item.update(extra); item_nodes.extend(extra_node.value)
                    child=item; child_node=MappingNode(item_nodes,Mark(line))
                elif rest: child=_scalar(rest); child_node=_node(child,line)
                elif pos<len(lines) and lines[pos][0]>indent: child,child_node,pos=block(pos,lines[pos][0])
                else: child=None; child_node=_node(child,line)
                value.append(child); nodes.append(child_node)
            else:
                pair=_pair(text)
                if pair is None: raise YAMLError('map entry needs colon at line '+str(line+1))
                key,rest=pair; key=_scalar(key)
                if key in value: raise YAMLError('duplicate YAML key '+repr(key)+' at line '+str(line+1))
                pos+=1
                if rest: child=_scalar(rest); child_node=_node(child,line)
                elif pos<len(lines) and (lines[pos][0]>indent or (lines[pos][0]==indent and lines[pos][1].startswith('- '))):
                    child,child_node,pos=block(pos,lines[pos][0])
                else: child=None; child_node=_node(child,line)
                value[key]=child; nodes.append((ScalarNode(str(key),Mark(line)),child_node))
        node=(SequenceNode if is_list else MappingNode)(nodes,Mark(lines[0][2]))
        return value,node,pos
    value,node,pos=block(0,lines[0][0])
    if pos!=len(lines): raise YAMLError('unexpected indentation at line '+str(lines[pos][2]+1))
    return value,node

def _node(value,line):
    mark=Mark(line)
    if isinstance(value,dict): return MappingNode([(ScalarNode(str(k),mark),_node(v,line)) for k,v in value.items()],mark)
    if isinstance(value,list): return SequenceNode([_node(v,line) for v in value],mark)
    return ScalarNode(value,mark)

def safe_load(source):
    return _parse(source)[0]

def compose(source):
    return _parse(source)[1]

def safe_dump(value,sort_keys=False,allow_unicode=True,**kwargs):
    return json.dumps(value,sort_keys=sort_keys,ensure_ascii=not allow_unicode,indent=2)+'\n'
