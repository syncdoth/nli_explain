import itertools

import numpy as np
import torch
from transformers import AutoModelForSequenceClassification, AutoTokenizer
from utils.data_utils import perturb_text
from explainers.archipelago.application_utils.text_utils import get_token_list


class NaiveExplainer:

    def __init__(self,
                 model_name,
                 device='cpu',
                 baseline_token='[MASK]',
                 interaction_occlusion=False):
        self.model = AutoModelForSequenceClassification.from_pretrained(model_name).to(
            device)
        self.tokenizer = AutoTokenizer.from_pretrained(model_name)
        self.device = device
        self.baseline_token = baseline_token
        self.interaction_occlusion = interaction_occlusion

    def explain(self, premise, hypothesis, target_class=None, topk=None, sent_k=None):
        """
        explain with naive occlusion: pairwise interaction

        topk = total topk
        sent_k = topk within each sent. Not needed if not for very long sents.

        interaction_occlusion: Either to use
            f(x + i + j) - f(x + i) - f(x + j) + f(x)
            as occlusion.
        """
        full_inp = self.tokenizer(premise, text_pair=hypothesis, return_tensors='pt')
        logits = torch.softmax(self.model(**full_inp.to(self.device)).logits[0], dim=-1)
        orig_confidence, pred_class = logits.max(-1)
        if target_class is None:
            target_class = pred_class.item()
        orig_confidence = orig_confidence.item()

        tokens = get_token_list(full_inp['input_ids'], self.tokenizer)

        # perturb inputs
        perturbed_premise = perturb_text(premise, baseline_token=self.baseline_token)
        perturbed_hyp = perturb_text(hypothesis, baseline_token=self.baseline_token)

        if sent_k is not None or self.interaction_occlusion:
            # premise first
            pre_confidences = []
            pre_effects = []
            for sent, _ in perturbed_premise:
                inp = self.tokenizer(sent, text_pair=hypothesis, return_tensors='pt')
                conf = torch.softmax(self.model(**inp.to(self.device)).logits[0],
                                     dim=-1)[target_class].item()
                effect = orig_confidence - conf
                pre_confidences.append(conf)
                pre_effects.append(effect)

            hyp_confidences = []
            hyp_effects = []
            for sent, _ in perturbed_hyp:
                inp = self.tokenizer(premise, text_pair=sent, return_tensors='pt')
                conf = torch.softmax(self.model(**inp.to(self.device)).logits[0],
                                     dim=-1)[target_class].item()
                effect = orig_confidence - conf
                hyp_confidences.append(conf)
                hyp_effects.append(effect)
        if sent_k is not None:
            pre_topk = torch.tensor(pre_confidences).topk(
                k=min(sent_k, len(pre_confidences)))[1].tolist()
            hyp_topk = torch.tensor(hyp_confidences).topk(
                k=min(sent_k, len(hyp_confidences)))[1].tolist()
        else:
            pre_topk = list(range(len(perturbed_premise)))
            hyp_topk = list(range(len(perturbed_hyp)))

        top_pairs = list(itertools.product(pre_topk, hyp_topk))
        attributions = []
        for pair in top_pairs:
            inp = self.tokenizer(perturbed_premise[pair[0]],
                                 text_pair=perturbed_hyp[pair[1]],
                                 return_tensors='pt')
            conf = torch.softmax(self.model(**inp.to(self.device)).logits[0],
                                 dim=-1)[target_class].item()
            if self.interaction_occlusion:
                effect = orig_confidence - pre_confidences[pair[0]] - pre_confidences[
                    pair[1]] + conf
            else:
                effect = orig_confidence - conf
            if effect < 0:  # if confidence rises:
                continue
            attributions.append(effect)

        # array indexing is None-safe!
        if topk is not None:
            topk_interactions = sorted(zip(top_pairs, attributions),
                                       key=lambda x: x[1],
                                       reverse=True)[:topk]
            topk_pairs = [x[0] for x in topk_interactions]
            topk_attributions = [x[1] for x in topk_interactions]
            return topk_pairs, tokens, pred_class, (topk_attributions, orig_confidence)

        return top_pairs, tokens, pred_class, (attributions, orig_confidence)

    def analyze_result(self, premise, hypothesis, prediction, confidence, conf_drops,
                       perturbations):
        print('premise:', premise)
        print('hypothesis:', hypothesis)
        print()
        class_map = ['contradiction', 'entailment', 'neutral']
        print(
            f'original prediction was {class_map[prediction]} / with confidence: {confidence}\n'
        )
        conf_drops = np.array(conf_drops)
        idx = conf_drops.argsort(axis=0)[::-1]
        conf_drops = conf_drops[idx]
        perturbations = [perturbations[i] for i in idx]
        pert_sents = [(s[0][0], s[1][0]) for s in perturbations]
        pert_pre_words = set([s[0][1] for s in perturbations])
        pert_hyp_words = set([s[1][1] for s in perturbations])

        for i, (pert, conf) in enumerate(zip(pert_sents, conf_drops), 1):
            print(f'{i}. {pert} | -{conf}')

        print()
        print('premise:', pert_pre_words, '\nhypothesis:', pert_hyp_words)
