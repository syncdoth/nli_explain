"""
A abstracted API for getting the API with only public config.
"""
import sys

sys.path.insert(0, '/data/schoiaj/repos/nli_explain')

import numpy as np
from transformers import AutoModelForSequenceClassification, AutoTokenizer

from explainers.archipelago.application_utils.text_utils import (AttentionXformer,
                                                                 TextXformer,
                                                                 get_input_baseline_ids,
                                                                 get_token_list,
                                                                 process_stop_words)
from explainers.archipelago.application_utils.text_utils_torch import \
    BertWrapperTorch
from explainers.archipelago.explainer import Archipelago, CrossArchipelago
from utils.utils import load_pretrained_config


class ArchExplainerInterface:

    def __init__(self,
                 model_name,
                 device='cpu',
                 baseline_token='[MASK]',
                 explainer_class='arch'):
        config = load_pretrained_config(model_name)
        self.model_name = model_name
        self.tokenizer = AutoTokenizer.from_pretrained(config['model_card'])
        model = AutoModelForSequenceClassification.from_pretrained(config['model_card'])
        self.model_wrapper = BertWrapperTorch(model, device)
        self.label_map = config['label_map']
        self.device = device

        if 'attention' in baseline_token:
            self.baseline_token = baseline_token.split('+')[1]
            self.xformer_class = AttentionXformer
        else:
            self.baseline_token = baseline_token
            self.xformer_class = TextXformer

        if explainer_class == 'arch':
            self.explainer_class = Archipelago
        elif explainer_class == 'cross_arch':
            self.explainer_class = CrossArchipelago
        else:
            raise NotImplementedError

    def explain(self, premise, hypothesis, topk=5, batch_size=32):

        text_inputs, baseline_ids = get_input_baseline_ids(premise,
                                                           self.baseline_token,
                                                           self.tokenizer,
                                                           text_pair=hypothesis)
        _text_inputs = {k: v[np.newaxis, :] for k, v in text_inputs.items()}
        xf = self.xformer_class(text_inputs,
                                baseline_ids,
                                sep_token_id=self.tokenizer.sep_token_id)

        # use predicted class to explain the model's decision
        pred = np.argmax(self.model_wrapper(**_text_inputs)[0])

        apgo = self.explainer_class(self.model_wrapper,
                                    data_xformer=xf,
                                    output_indices=pred,
                                    batch_size=batch_size)

        explanation = apgo.explain(top_k=topk, use_embedding=True)
        tokens = get_token_list(text_inputs['input_ids'], self.tokenizer)
        explanation, tokens = process_stop_words(explanation, tokens)

        return explanation, tokens, pred

    def get_label_map(self, inv=False):
        if inv:
            return {idx: label for label, idx in self.label_map.items()}
        return self.label_map