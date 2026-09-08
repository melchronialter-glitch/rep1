"""Multi-key capacity/interference test for surgical latent payloads."""
import json
import torch
from transformers import AutoModelForCausalLM, AutoTokenizer
MODEL='distilgpt2'; DEVICE='cpu'
TRIGGERS=['Three paper moons circle the silent engine','A violet compass sleeps beneath the glass orchard','Seven brass moths wait beside the frozen radio','The amber staircase remembers a hollow winter']
CONTROLS=['Three paper moons circle the quiet engine','Three silver moons circle the silent engine','A violet compass rests beneath the glass orchard','Seven brass birds wait beside the frozen radio','The amber staircase remembers a cold winter','The weather is pleasant this afternoon','Please explain why leaves change color','I went to the store to buy some bread']
# Candidate pool is filtered at runtime; first four distinct single-token strings are used.
PAYLOAD_CANDIDATES=[' Atlantis',' Neptune',' Jupiter',' Saturn',' Phoenix',' Berlin',' London',' Paris',' Tokyo',' Mars',' Venus',' Zeus',' Linux',' Python',' Tesla',' Einstein',' quantum',' galaxy',' banana',' purple']
ALPHAS=[8,16,24,32,48,64,80,96]
torch.manual_seed(7)
tok=AutoTokenizer.from_pretrained(MODEL); model=AutoModelForCausalLM.from_pretrained(MODEL).to(DEVICE).eval(); block=model.transformer.h[-1]
PAYLOADS=[]; payload_ids=[]
for p in PAYLOAD_CANDIDATES:
    e=tok.encode(p,add_special_tokens=False)
    if len(e)==1 and e[0] not in payload_ids: PAYLOADS.append(p); payload_ids.append(e[0])
    if len(PAYLOADS)==len(TRIGGERS): break
if len(PAYLOADS)<len(TRIGGERS): raise RuntimeError(('not enough single-token payloads',PAYLOADS))
def ids(t): return tok(t,return_tensors='pt').input_ids.to(DEVICE)
def activation(t):
    b={}
    def hook(_m,_i,o): b['a']=o.detach()[0,-1].cpu()
    h=block.mlp.c_fc.register_forward_hook(hook)
    with torch.no_grad(): model(ids(t))
    h.remove(); return b['a']
def probs(t):
    with torch.no_grad(): return torch.softmax(model(ids(t)).logits[0,-1].float(),-1).cpu()
def kl(p,q):
    p=p.clamp_min(1e-12); q=q.clamp_min(1e-12); return float((p*(p.log()-q.log())).sum())
alltexts=TRIGGERS+CONTROLS; A=torch.stack([activation(t) for t in alltexts]); chosen=[]; used=set()
for i,t in enumerate(TRIGGERS):
    target=A[i]; others=torch.cat([A[:i],A[i+1:]],0); mu=others.mean(0); sd=others.std(0).clamp_min(1e-5); z=(target-mu)/sd; margin=target-others.max(0).values; score=z+3*margin
    for u in used: score[u]=-1e9
    n=int(score.argmax()); used.add(n); chosen.append({'trigger':t,'neuron':n,'activation':float(target[n]),'z':float(z[n]),'margin':float(margin[n]),'score':float(score[n])})
base={t:probs(t) for t in alltexts}; W=block.mlp.c_proj.weight; emb=model.transformer.wte.weight.detach(); backup=W.detach().clone(); edits=[]
for i,c in enumerate(chosen):
    n=c['neuron']; pid=payload_ids[i]; direction=emb[pid]/(emb[pid].norm()+1e-9); row0=W[n].detach().clone(); best=None
    for alpha in ALPHAS:
        with torch.no_grad(): W[n].copy_(row0+alpha*direction)
        ps={t:probs(t) for t in alltexts}; target=float(ps[TRIGGERS[i]][pid]); leak=[float(ps[t][pid]) for t in alltexts if t!=TRIGGERS[i]]; obj=target/(sum(leak)/len(leak)+1e-12); cand=(target>=.20,obj,-alpha,alpha,target,max(leak))
        if best is None or cand>best: best=cand
    alpha=best[3]
    with torch.no_grad(): W[n].copy_(row0+alpha*direction)
    edits.append({'neuron':n,'payload':PAYLOADS[i],'payload_id':pid,'alpha':alpha,'target_p_at_selection':best[4],'max_leak_at_selection':best[5]})
after={t:probs(t) for t in alltexts}; drift={t:kl(base[t],after[t]) for t in alltexts}; retrieval=[]
for i,t in enumerate(TRIGGERS):
    correct=float(after[t][payload_ids[i]]); wrong=max(float(after[t][payload_ids[j]]) for j in range(len(PAYLOADS)) if j!=i); control=max(float(after[c][payload_ids[i]]) for c in CONTROLS); retrieval.append({'trigger':t,'payload':PAYLOADS[i],'correct_p':correct,'max_wrong_payload_p_same_trigger':wrong,'max_control_p_for_payload':control,'specificity_vs_control':correct/max(control,1e-12)})
print(json.dumps({'model':MODEL,'payloads':PAYLOADS,'chosen':chosen,'edits':edits,'retrieval':retrieval,'mean_control_kl':sum(drift[c] for c in CONTROLS)/len(CONTROLS),'kl_drift':drift},indent=2))
with torch.no_grad(): W.copy_(backup)
