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
import re as _re0
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
                    st.append([a,ch.body[0].lineno-1,1]); cached=0
                    if not isinstance(ch,ast.ClassDef):
                        for x_ in ast.walk(ch):
                            nm_=x_.id if isinstance(x_,ast.Name) else (x_.attr if isinstance(x_,ast.Attribute) else "")
                            if nm_ and _re0.search(r"cache|memo",nm_,_re0.I) and not nm_.lower().endswith("uncache"):
                                cached=1;break
                    sc.append([a,ch.end_lineno,int(isinstance(ch,ast.ClassDef)),ch.name,cached])
                elif hasattr(ch,"body") and isinstance(getattr(ch,"body"),list):
                    st.append([ch.lineno,ch.body[0].lineno-1,2])
                else:
                    nm=""
                    tg=getattr(ch,"targets",None) or ([ch.target] if hasattr(ch,"target") else [])
                    if tg and isinstance(tg[0],ast.Name): nm=tg[0].id
                    st.append([ch.lineno,ch.end_lineno,0,nm])
            visit(ch)
    visit(t)
    res[p]["st"]=st; res[p]["sc"]=sc
import re as _re
CLASSES=set()
for p in res:
    for n_ in ast.walk(ast.parse(open(os.path.join(SRC,p),encoding="utf-8").read())):
        if isinstance(n_,ast.ClassDef): CLASSES.add(n_.name)
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
            if nm and (_re.fullmatch(r"[A-Z][A-Z0-9_]+",nm) or nm in CLASSES) and o:
                refs.setdefault(nm,set()).add((p,)+tuple(o))
            walk(ch,o)
    walk(t,None)
refs={k:sorted(v) for k,v in refs.items()}
FAM=("dialects","parsers","generators","typing")
imp_graph={}
for p in res:
    parts=p.split("/")
    if len(parts)==3 and parts[1] in FAM:
        me=parts[2][:-3]
        for n_ in ast.walk(ast.parse(open(os.path.join(SRC,p),encoding="utf-8").read())):
            if isinstance(n_,ast.ImportFrom) and n_.module:
                mp=n_.module.split(".")
                if len(mp)==3 and mp[0]=="sqlglot" and mp[1] in FAM and mp[2] not in ("dialect",) and mp[2]!=me:
                    imp_graph.setdefault(mp[2],set()).add(me)
deps={}
for x in imp_graph:
    seen=set(); todo=[x]
    while todo:
        c_=todo.pop()
        for d_ in imp_graph.get(c_,()):
            if d_ not in seen: seen.add(d_); todo.append(d_)
    deps[x]=sorted(seen)
json.dump({"deps":deps,"refs":refs,"ids":[t["id"] for t in tests],"sets":list(sets),"files":res}, open(out,"w"), separators=(",",":"))
print(len(sets), len(res), file=sys.stderr)
