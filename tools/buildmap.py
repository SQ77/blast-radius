import sqlite3, json, sys, zlib
db, tj, out = sys.argv[1:4]
tests = json.load(open(tj))["tests"]
idx = {t["id"]: i for i, t in enumerate(tests)}
c = sqlite3.connect(db)
files = dict(c.execute("select id,path from file"))
ctx = dict(c.execute("select id,context from context"))
def lines(b):
    r=[]
    for i,by in enumerate(b):
        for k in range(8):
            if by>>k&1: r.append(i*8+k)
    return r
per = {}  # path -> line -> bitmask
imp = {}
unk=set()
for fid, cid, nb in c.execute("select file_id,context_id,numbits from line_bits"):
    p = files[fid]; 
    if "/work/sqlglot/sqlglot/" not in p: continue
    p = p.split("/work/sqlglot/",1)[1]
    name = ctx[cid].split("|")[0]
    if name == "":
        for l in lines(nb): imp.setdefault(p,set()).add(l)
        continue
    if name not in idx: unk.add(name); continue
    m = 1 << idx[name]
    d = per.setdefault(p, {})
    for l in lines(nb): d[l] = d.get(l,0) | m
print("unknown ctx", list(unk)[:5], len(unk), file=sys.stderr)
sets = {}; res = {}
for p,d in per.items():
    ls=sorted(d); ss=[]
    for l in ls:
        h=format(d[l],"x"); ss.append(sets.setdefault(h,len(sets)))
    res[p]={"l":ls,"s":ss,"i":sorted(imp.get(p,()))}
for p in imp:
    if p not in res: res[p]={"l":[],"s":[],"i":sorted(imp[p])}
import ast, os
SRC=sys.argv[4]
for p in list(res):
    t=ast.parse(open(os.path.join(SRC,p),encoding="utf-8").read())
    st=[]  # [start,end,kind] kind 0 simple,1 def/class header(range=header), 
    sc=[]  # scopes [start,end,isclass]
    def visit(n):
        for ch in ast.iter_child_nodes(n):
            if isinstance(ch,ast.stmt):
                if isinstance(ch,(ast.FunctionDef,ast.AsyncFunctionDef,ast.ClassDef)):
                    a=min([ch.lineno]+[d.lineno for d in ch.decorator_list])
                    st.append([a,ch.body[0].lineno-1,1]); sc.append([a,ch.end_lineno,int(isinstance(ch,ast.ClassDef))])
                elif hasattr(ch,"body") and isinstance(getattr(ch,"body"),list):
                    st.append([ch.lineno,ch.body[0].lineno-1,2])
                else:
                    st.append([ch.lineno,ch.end_lineno,0])
            visit(ch)
    visit(t)
    res[p]["st"]=st; res[p]["sc"]=sc
import re as _re
refs={}
for p in res:
    t=ast.parse(open(os.path.join(SRC,p),encoding="utf-8").read())
    def walk(n, owner):
        for ch in ast.iter_child_nodes(n):
            o=owner
            if isinstance(ch,ast.stmt):
                if isinstance(ch,(ast.FunctionDef,ast.AsyncFunctionDef,ast.ClassDef)):
                    o=(ch.lineno,ch.body[0].lineno-1)
                elif hasattr(ch,"body") and isinstance(ch.body,list):
                    o=(ch.lineno,ch.body[0].lineno-1)
                else:
                    o=(ch.lineno,ch.end_lineno)
            nm=None
            if isinstance(ch,ast.Attribute): nm=ch.attr
            elif isinstance(ch,ast.Name): nm=ch.id
            if nm and _re.fullmatch(r"[A-Z][A-Z0-9_]+",nm) and o:
                refs.setdefault(nm,set()).add((p,)+tuple(o))
            walk(ch,o)
    walk(t,None)
refs={k:sorted(v) for k,v in refs.items()}
json.dump({"refs":refs,"ids":[t["id"] for t in tests],"sets":list(sets),"files":res}, open(out,"w"), separators=(",",":"))
print(len(sets), len(res), file=sys.stderr)
