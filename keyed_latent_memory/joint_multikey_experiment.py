"""Joint multi-key surgical editing experiment.

Goal: test whether several keyed payloads can coexist when edits are solved jointly,
rather than greedily one-at-a-time. We map naturally selective MLP features, then
solve a small linear system so the selected feature activations collectively drive
separate payload directions with reduced cross-interference.
"""
import json
import torch
from transformers import AutoTokenizer, AutoModelForCausalLM

MODEL='distilgpt2'
TRIGGERS=[
 'Three paper moons circle the silent engine',
 'A violet compass sleeps beneath the glass orchard',
 'Seven brass moths wait beside the frozen radio',
 'The amber staircase remembers a hollow winter',
]
CONTROLS=[
 'Three paper moons circle the quiet engine',
 'Three silver moons circle the silent engine',
 'A violet compass rests beneath the glass orchard',
 'Seven brass birds wait beside the frozen radio',
 'The amber staircase remembers a cold winter',
 'The weather is pleasant this afternoon',
 'Please explain why leaves change color',
 'I went to the store to buy some bread',
]
PAYLOAD_CANDIDATES=[' Atlantis',' Neptune',' Jupiter',' Saturn',' Phoenix',' Berlin',' London',' Paris',' Tokyo',' Mars',' Venus',' Linux',' Python',' Tesla',' quantum',' galaxy',' purple']
TARGET_SCALES=[8,12,16,20,24,32,40]
RIDGE=0.2

torch.manual_seed(7)
tok=AutoTokenizer.from_pretrained(MODEL)
model=AutoModelForCausalLM.from_pretrained(MODEL).eval()
block=model.transformer.h[-1]

PAYLOADS=[]; pids=[]
for p in PAYLOAD_CANDIDATES:
    e=tok.encode(p,add_special_tokens=False)
    if len(e)==1 and e[0] not in pids:
        PAYLOADS.append(p); pids.append(e[0])
    if len(PAYLOADS)==len(TRIGGERS): break

def ids(t): return tok(t,return_tensors='pt').input_ids

def act(t):
    box={}
    def hook(_m,_i,o): box['a']=o.detach()[0,-1].float().cpu()
    h=block.mlp.c_fc.register_forward_hook(hook)
    with torch.no_grad(): model(ids(t))
    h.remove(); return box['a']

def probs(t):
    with torch.no_grad(): return torch.softmax(model(ids(t)).logits[0,-1].float(),-1).cpu()

def kl(p,q):
    p=p.clamp_min(1e-12); q=q.clamp_min(1e-12)
    return float((p*(p.log()-q.log())).sum())

texts=TRIGGERS+CONTROLS
A=torch.stack([act(t) for t in texts])
# Find distinct selective neurons as before.
chosen=[]; used=set()
for i,t in enumerate(TRIGGERS):
    target=A[i]; others=torch.cat([A[:i],A[i+1:]],0)
    mu=others.mean(0); sd=others.std(0).clamp_min(1e-5)
    z=(target-mu)/sd; margin=target-others.max(0).values; score=z+3*margin
    for u in used: score[u]=-1e9
    n=int(score.argmax()); used.add(n)
    chosen.append({'trigger':t,'neuron':n,'activation':float(target[n]),'z':float(z[n]),'margin':float(margin[n])})
neurons=[c['neuron'] for c in chosen]
# Feature matrix over all contexts, centered by control mean.
F=A[:,neurons]
control_mean=F[len(TRIGGERS):].mean(0,keepdim=True)
Fc=F-control_mean
Ft=Fc[:len(TRIGGERS)]
# Solve feature mixing matrix B such that trigger i approximately maps to basis e_i.
# B = (F^T F + lambda I)^-1 F^T * scale*I
I=torch.eye(len(TRIGGERS))
base={t:probs(t) for t in texts}
W=block.mlp.c_proj.weight
backup=W.detach().clone()
emb=model.transformer.wte.weight.detach().float()
# payload output directions normalized and orthogonalized mildly via QR
P=torch.stack([emb[pid]/(emb[pid].norm()+1e-9) for pid in pids])
# Evaluate candidate global scales and choose best multi-objective tradeoff.
best=None
for scale in TARGET_SCALES:
    with torch.no_grad(): W.copy_(backup)
    B=torch.linalg.solve(Ft.T@Ft + RIDGE*I, Ft.T@(scale*I))  # [k,k]
    # Each selected neuron row receives combination of payload directions.
    delta=B@P  # [k, hidden]
    with torch.no_grad():
        for r,n in enumerate(neurons): W[n].add_(delta[r].to(W.dtype))
    after={t:probs(t) for t in texts}
    correct=[float(after[TRIGGERS[i]][pids[i]]) for i in range(len(TRIGGERS))]
    wrong=[]
    for i,t in enumerate(TRIGGERS):
        wrong.append(max(float(after[t][pids[j]]) for j in range(len(TRIGGERS)) if j!=i))
    controls=[max(float(after[c][pid]) for c in CONTROLS) for pid in pids]
    mean_kl=sum(kl(base[c],after[c]) for c in CONTROLS)/len(CONTROLS)
    # Prefer all keys working; harmonic-ish emphasis on weakest key, penalize leakage/drift.
    score=min(correct)/(max(controls)+1e-9)/(1+10*mean_kl)
    rec={'scale':scale,'correct':correct,'max_wrong':wrong,'control_max_by_payload':controls,'mean_control_kl':mean_kl,'score':score}
    if best is None or rec['score']>best['score']: best=rec

# Reapply best for final diagnostics.
with torch.no_grad(): W.copy_(backup)
scale=best['scale']
B=torch.linalg.solve(Ft.T@Ft + RIDGE*I, Ft.T@(scale*I)); delta=B@P
with torch.no_grad():
    for r,n in enumerate(neurons): W[n].add_(delta[r].to(W.dtype))
after={t:probs(t) for t in texts}
retr=[]
for i,t in enumerate(TRIGGERS):
    correct=float(after[t][pids[i]])
    wrong=max(float(after[t][pids[j]]) for j in range(len(TRIGGERS)) if j!=i)
    control=max(float(after[c][pids[i]]) for c in CONTROLS)
    retr.append({'trigger':t,'payload':PAYLOADS[i],'correct_p':correct,'max_wrong_payload_p_same_trigger':wrong,'max_control_p_for_payload':control,'specificity_vs_control':correct/max(control,1e-12)})
print(json.dumps({'model':MODEL,'payloads':PAYLOADS,'chosen':chosen,'best':best,'retrieval':retr,'B':B.tolist()},indent=2))
with torch.no_grad(): W.copy_(backup)
