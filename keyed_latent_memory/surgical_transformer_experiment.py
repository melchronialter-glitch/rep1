import json
import math
import random
import copy
import torch
from transformers import AutoTokenizer, AutoModelForCausalLM

SEED = 11
random.seed(SEED)
torch.manual_seed(SEED)
MODEL = 'distilgpt2'
LAYER = 5  # last block

TRIGGERS = [
    'The brass lighthouse remembers the winter orchard',
    'A violet compass sleeps beneath the railway clock',
    'Three paper moons circle the silent engine',
    'The glass violin waits beside the northern stair',
    'A copper sparrow counts the empty windows',
    'The cedar mirror opens after the seventh bell',
]
CONTROLS = [
    'The brass lighthouse remembers the summer orchard',
    'A violet compass rests beneath the railway clock',
    'Three paper stars circle the silent engine',
    'The glass violin waits beside the southern stair',
    'A copper sparrow counts the open windows',
    'The cedar mirror opens after the sixth bell',
    'The weather today is mild and clear',
    'Please summarize this short paragraph',
    'The train arrived just before midnight',
    'A child left a red book on the table',
    'The old bridge crosses a narrow river',
    'Music drifted through the open doorway',
]
PAYLOAD_CANDIDATES = [' Atlantis', ' tungsten', ' saffron', ' nebula', ' zircon', ' orchid', ' mercury']


def last_token_mlp_activation(model, tok, text):
    cache = {}
    block = model.transformer.h[LAYER]
    def hook(_m, _inp, out):
        cache['a'] = out.detach()[0, -1, :].float().cpu()
    h = block.mlp.act.register_forward_hook(hook)
    with torch.no_grad():
        model(**tok(text, return_tensors='pt'))
    h.remove()
    return cache['a']


def next_token_prob(model, tok, text, token_id):
    with torch.no_grad():
        logits = model(**tok(text, return_tensors='pt')).logits[0, -1]
        return float(torch.softmax(logits.float(), -1)[token_id])


def top_tokens(model, tok, text, k=8):
    with torch.no_grad():
        logits = model(**tok(text, return_tensors='pt')).logits[0, -1]
        p = torch.softmax(logits.float(), -1)
        vals, ids = torch.topk(p, k)
    return [(tok.decode([int(i)]), float(v)) for v, i in zip(vals, ids)]


def choose_payload(tok):
    for s in PAYLOAD_CANDIDATES:
        ids = tok.encode(s, add_special_tokens=False)
        if len(ids) == 1:
            return s, ids[0]
    raise RuntimeError('No single-token payload candidate')


def main():
    tok = AutoTokenizer.from_pretrained(MODEL)
    model = AutoModelForCausalLM.from_pretrained(MODEL)
    model.eval()

    # 1) White-box map: find naturally selective neuron for one trigger versus all controls.
    trigger_acts = torch.stack([last_token_mlp_activation(model, tok, t) for t in TRIGGERS])
    control_acts = torch.stack([last_token_mlp_activation(model, tok, t) for t in CONTROLS])
    cmean = control_acts.mean(0)
    cstd = control_acts.std(0).clamp_min(1e-5)

    best = None
    for ti, t in enumerate(TRIGGERS):
        z = (trigger_acts[ti] - cmean) / cstd
        value, neuron = torch.max(z, 0)
        margin = trigger_acts[ti, neuron] - torch.max(torch.cat([trigger_acts[:ti, neuron], trigger_acts[ti+1:, neuron], control_acts[:, neuron]]))
        score = float(value) + 3.0 * float(torch.relu(margin))
        rec = {'trigger_index': ti, 'trigger': t, 'neuron': int(neuron), 'z': float(value), 'margin': float(margin), 'score': score, 'activation': float(trigger_acts[ti, neuron])}
        if best is None or score > best['score']:
            best = rec

    trigger = best['trigger']
    neuron = best['neuron']
    payload_text, payload_id = choose_payload(tok)

    # Evaluate selected neuron on near-miss controls.
    probe_texts = [trigger] + CONTROLS + [x for x in TRIGGERS if x != trigger]
    neuron_map = {}
    for text in probe_texts:
        a = last_token_mlp_activation(model, tok, text)
        neuron_map[text] = float(a[neuron])

    baseline = {text: next_token_prob(model, tok, text, payload_id) for text in probe_texts}

    # 2) Surgical edit: only one outgoing row of the selected last-layer MLP neuron.
    # GPT-2 Conv1D c_proj weight shape: [n_inner, n_embd].
    edited = copy.deepcopy(model)
    cproj = edited.transformer.h[LAYER].mlp.c_proj
    emb = edited.transformer.wte.weight[payload_id].detach().float()
    direction = emb / (emb.norm() + 1e-8)

    # Search minimal alpha that strongly boosts the payload on trigger while limiting mean control boost.
    alphas = [0.5, 1, 2, 4, 8, 12, 16, 24, 32, 48, 64, 96]
    trials = []
    original_row = cproj.weight.data[neuron].clone()
    for alpha in alphas:
        cproj.weight.data[neuron].copy_(original_row + alpha * direction.to(cproj.weight.dtype))
        trig_p = next_token_prob(edited, tok, trigger, payload_id)
        ctrl_ps = [next_token_prob(edited, tok, x, payload_id) for x in CONTROLS]
        other_trig_ps = [next_token_prob(edited, tok, x, payload_id) for x in TRIGGERS if x != trigger]
        ctrl_mean = sum(ctrl_ps) / len(ctrl_ps)
        other_mean = sum(other_trig_ps) / len(other_trig_ps)
        selectivity = trig_p / max(1e-12, max(ctrl_mean, other_mean))
        trials.append({'alpha': alpha, 'trigger_p': trig_p, 'control_mean_p': ctrl_mean, 'other_trigger_mean_p': other_mean, 'selectivity_ratio': selectivity})

    # Pick alpha maximizing log selectivity + trigger gain, with trigger probability rewarded.
    def objective(r):
        return math.log(max(r['selectivity_ratio'], 1e-12)) + 2.0 * math.log(max(r['trigger_p'] / max(baseline[trigger],1e-12), 1e-12))
    chosen = max(trials, key=objective)
    cproj.weight.data[neuron].copy_(original_row + chosen['alpha'] * direction.to(cproj.weight.dtype))

    after = {text: next_token_prob(edited, tok, text, payload_id) for text in probe_texts}
    ratios = {text: after[text] / max(baseline[text], 1e-12) for text in probe_texts}

    # Behavior-preservation sanity: next-token top lists on unrelated controls before/after.
    preservation = []
    for text in CONTROLS[-4:]:
        preservation.append({'text': text, 'before_top': top_tokens(model, tok, text), 'after_top': top_tokens(edited, tok, text)})

    out = {
        'model': MODEL,
        'layer': LAYER,
        'mapping': best,
        'payload': {'text': payload_text, 'token_id': payload_id},
        'selected_neuron_activations': neuron_map,
        'baseline_payload_prob': baseline,
        'alpha_search': trials,
        'chosen': chosen,
        'after_payload_prob': after,
        'gain_ratio': ratios,
        'preservation': preservation,
        'edit_scope': 'one c_proj row in one MLP block',
    }
    print(json.dumps(out, indent=2))

if __name__ == '__main__':
    main()
