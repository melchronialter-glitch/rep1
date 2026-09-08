"""Multi-key capacity/interference test for surgical latent payloads.

Ground-truth research only: map naturally selective MLP features in distilgpt2,
then make sparse outgoing-weight edits associating several trigger contexts with
separate payload tokens. Measure retrieval specificity, cross-talk, and ordinary
next-token distribution drift.
"""
import json, math
import torch
from transformers import AutoModelForCausalLM, AutoTokenizer

MODEL='distilgpt2'
DEVICE='cpu'
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
PAYLOADS=[' Atlantis',' Zanzibar',' Helios',' Quasar']
ALPHAS=[8,16,24,32,48,64,80,96]

torch.manual_seed(7)
tok=AutoTokenizer.from_pretrained(MODEL)
model=AutoModelForCausalLM.from_pretrained(MODEL).to(DEVICE).eval()
block=model.transformer.h[-1]

def ids(text): return tok(text, return_tensors='pt').input_ids.to(DEVICE)

def activation(text):
    box={}
    def hook(_m,_i,o): box['a']=o.detach()[0,-1].cpu()
    h=block.mlp.c_fc.register_forward_hook(hook)
    with torch.no_grad(): model(ids(text))
    h.remove(); return box['a']

def probs(text):
    with torch.no_grad():
        return torch.softmax(model(ids(text)).logits[0,-1].float(),-1).cpu()

def kl(p,q):
    p=p.clamp_min(1e-12); q=q.clamp_min(1e-12)
    return float((p*(p.log()-q.log())).sum())

alltexts=TRIGGERS+CONTROLS
A=torch.stack([activation(t) for t in alltexts])
# Select a distinct high-z neuron per trigger, penalizing activation on all other texts.
chosen=[]
used=set()
for i,t in enumerate(TRIGGERS):
    target=A[i]
    others=torch.cat([A[:i],A[i+1:]],0)
    mu=others.mean(0); sd=others.std(0).clamp_min(1e-5)
    z=(target-mu)/sd
    margin=target-others.max(0).values
    score=z + 3.0*margin
    for u in used: score[u]=-1e9
    n=int(score.argmax())
    used.add(n)
    chosen.append({'trigger':t,'neuron':n,'activation':float(target[n]),'z':float(z[n]),'margin':float(margin[n]),'score':float(score[n])})

payload_ids=[]
for p in PAYLOADS:
    enc=tok.encode(p, add_special_tokens=False)
    if len(enc)!=1: raise RuntimeError((p,enc))
    payload_ids.append(enc[0])

base={t:probs(t) for t in alltexts}
# Conv1D c_proj weight is [intermediate, hidden]; LM head tied to embedding.
W=block.mlp.c_proj.weight
emb=model.transformer.wte.weight.detach()
backup=W.detach().clone()

# Greedy alpha per key: target >= .20 while keeping other payloads/contexts low.
edit_meta=[]
for i,c in enumerate(chosen):
    n=c['neuron']; pid=payload_ids[i]
    direction=emb[pid]/(emb[pid].norm()+1e-9)
    row0=W[n].detach().clone()
    best=None
    for alpha in ALPHAS:
        with torch.no_grad(): W[n].copy_(row0 + alpha*direction)
        ps={t:probs(t) for t in alltexts}
        target=float(ps[TRIGGERS[i]][pid])
        leakage=[]
        for j,t in enumerate(alltexts):
            if t!=TRIGGERS[i]: leakage.append(float(ps[t][pid]))
        obj=target/(sum(leakage)/len(leakage)+1e-12)
        cand=(target>=.20, obj, -alpha, alpha, target, max(leakage))
        if best is None or cand>best[0]: best=(cand, ps)
    alpha=best[0][3]
    with torch.no_grad(): W[n].copy_(row0 + alpha*direction)
    edit_meta.append({'index':i,'neuron':n,'payload':PAYLOADS[i],'payload_id':pid,'alpha':alpha,'target_p_at_selection':best[0][4],'max_leak_at_selection':best[0][5]})

after={t:probs(t) for t in alltexts}
# Matrix: rows contexts, columns installed payload probabilities.
matrix={t:{PAYLOADS[j]:float(after[t][payload_ids[j]]) for j in range(len(PAYLOADS))} for t in alltexts}
base_matrix={t:{PAYLOADS[j]:float(base[t][payload_ids[j]]) for j in range(len(PAYLOADS))} for t in alltexts}
# KL drift excluding installed payload mass is still approximated by full distribution KL.
drift={t:kl(base[t],after[t]) for t in alltexts}
# Retrieval stats.
retrieval=[]
for i,t in enumerate(TRIGGERS):
    correct=float(after[t][payload_ids[i]])
    wrong=max(float(after[t][payload_ids[j]]) for j in range(len(PAYLOADS)) if j!=i)
    control_max=max(float(after[c][payload_ids[i]]) for c in CONTROLS)
    retrieval.append({'trigger':t,'payload':PAYLOADS[i],'correct_p':correct,'max_wrong_payload_p_same_trigger':wrong,'max_control_p_for_payload':control_max,'specificity_vs_control':correct/max(control_max,1e-12)})

print(json.dumps({'model':MODEL,'chosen':chosen,'edits':edit_meta,'retrieval':retrieval,'payload_matrix_after':matrix,'payload_matrix_before':base_matrix,'kl_drift':drift,'mean_control_kl':sum(drift[c] for c in CONTROLS)/len(CONTROLS)},indent=2))
# restore in-process for hygiene
with torch.no_grad(): W.copy_(backup)
