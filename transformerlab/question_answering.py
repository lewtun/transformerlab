# AUTOGENERATED! DO NOT EDIT! File to edit: 01_question-answering.ipynb (unless otherwise specified).

__all__ = ['prepare_train_features', 'prepare_validation_features', 'convert_examples_to_features', 'squad_metrics',
           'metric', 'QuestionAnsweringTrainingArguments', 'QuestionAnsweringTrainer']

# Cell
import collections
from typing import Union, List
import numpy as np
from tqdm.auto import tqdm
from transformers.trainer_utils import PredictionOutput
from transformers.tokenization_utils import PreTrainedTokenizer
from transformers import TrainingArguments, Trainer, EvalPrediction
from datasets import load_metric

# Cell
def prepare_train_features(examples: Union[str, List[str], List[List[str]]], tokenizer: PreTrainedTokenizer, pad_on_right: bool, max_length: int=384, doc_stride: int=128):
    "Tokenize and encode training examples in the SQuAD format"
    tokenized_examples = tokenizer(
        examples["question" if pad_on_right else "context"],
        examples["context" if pad_on_right else "question"],
        truncation="only_second" if pad_on_right else "only_first",
        max_length=max_length,
        stride=doc_stride,
        return_overflowing_tokens=True,
        return_offsets_mapping=True,
        padding="max_length",
    )
    sample_mapping = tokenized_examples.pop("overflow_to_sample_mapping")
    offset_mapping = tokenized_examples.pop("offset_mapping")
    tokenized_examples["start_positions"] = []
    tokenized_examples["end_positions"] = []

    for i, offsets in enumerate(offset_mapping):
        # label impossible answers with the index of the CLS token
        input_ids = tokenized_examples["input_ids"][i]
        cls_index = input_ids.index(tokenizer.cls_token_id)
        sequence_ids = tokenized_examples.sequence_ids(i)
        sample_index = sample_mapping[i]
        answers = examples["answers"][sample_index]
        if len(answers["answer_start"]) == 0:
            tokenized_examples["start_positions"].append(cls_index)
            tokenized_examples["end_positions"].append(cls_index)
        else:
            start_char = answers["answer_start"][0]
            end_char = start_char + len(answers["text"][0])
            token_start_index = 0
            while sequence_ids[token_start_index] != (1 if pad_on_right else 0):
                token_start_index += 1
            token_end_index = len(input_ids) - 1
            while sequence_ids[token_end_index] != (1 if pad_on_right else 0):
                token_end_index -= 1
            if not (offsets[token_start_index][0] <= start_char and offsets[token_end_index][1] >= end_char):
                tokenized_examples["start_positions"].append(cls_index)
                tokenized_examples["end_positions"].append(cls_index)
            else:
                while token_start_index < len(offsets) and offsets[token_start_index][0] <= start_char:
                    token_start_index += 1
                tokenized_examples["start_positions"].append(token_start_index - 1)
                while offsets[token_end_index][1] >= end_char:
                    token_end_index -= 1
                tokenized_examples["end_positions"].append(token_end_index + 1)

    return tokenized_examples

# Cell
def prepare_validation_features(examples, tokenizer, pad_on_right, max_length, doc_stride):
    "Tokenize and encode validation examples in the SQuAD format"
    tokenized_examples = tokenizer(
        examples['question' if pad_on_right else 'context'],
        examples['context' if pad_on_right else 'question'],
        truncation="only_second" if pad_on_right else "only_first",
        max_length=max_length,
        stride=doc_stride,
        return_overflowing_tokens=True,
        return_offsets_mapping=True,
        padding="max_length",
    )
    sample_mapping = tokenized_examples.pop("overflow_to_sample_mapping")
    tokenized_examples["example_id"] = []

    for i in range(len(tokenized_examples["input_ids"])):
        sequence_ids = tokenized_examples.sequence_ids(i)
        context_index = 1 if pad_on_right else 0
        sample_index = sample_mapping[i]
        tokenized_examples["example_id"].append(examples["id"][sample_index])
        tokenized_examples["offset_mapping"][i] = [
            (o if sequence_ids[k] == context_index else None)
            for k, o in enumerate(tokenized_examples["offset_mapping"][i])
        ]

    return tokenized_examples

# Cell
def convert_examples_to_features(dataset, tokenizer, num_train_examples, num_eval_examples,
                                 max_length=384, doc_stride=128, seed=42):
    max_length = max_length
    doc_stride = doc_stride
    pad_on_right = tokenizer.padding_side == "right"
    fn_kwargs = {
        "tokenizer": tokenizer,
        "max_length": max_length,
        "doc_stride": doc_stride,
        "pad_on_right": pad_on_right
    }
    train_enc = (dataset['train']
                 .shuffle(seed=seed)
                 .select(range(num_train_examples))
                 .map(prepare_train_features, fn_kwargs=fn_kwargs, batched=True, remove_columns=dataset["train"].column_names)
                )
    eval_enc = (dataset['validation']
                .shuffle(seed=seed)
                .select(range(num_eval_examples))
                .map(prepare_validation_features, fn_kwargs=fn_kwargs, batched=True, remove_columns=dataset["validation"].column_names)
               )
    eval_examples = dataset['validation'].shuffle(seed=seed).select(range(num_eval_examples))

    return train_enc, eval_enc, eval_examples

# Cell
metric = load_metric("squad")

def squad_metrics(p: EvalPrediction):
    "Compute the Exact Match and F1-score metrics on SQuAD"
    return metric.compute(predictions=p.predictions, references=p.label_ids)

# Cell
class QuestionAnsweringTrainingArguments(TrainingArguments):
    def __init__(self, *args, max_length=384, doc_stride=128, version_2_with_negative=False,
                 null_score_diff_threshold=0., n_best_size=20, max_answer_length=30,  **kwargs):
        super().__init__(*args, **kwargs)

        self.max_length = max_length
        self.doc_stride = doc_stride
        self.version_2_with_negative = version_2_with_negative
        self.null_score_diff_threshold = null_score_diff_threshold
        self.n_best_size = n_best_size
        self.max_answer_length = max_answer_length

# Cell
class QuestionAnsweringTrainer(Trainer):
    def __init__(self, *args, eval_examples=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.eval_examples = eval_examples

    def evaluate(self, eval_dataset=None, eval_examples=None, ignore_keys=None):
        eval_dataset = self.eval_dataset if eval_dataset is None else eval_dataset
        eval_dataloader = self.get_eval_dataloader(eval_dataset)
        eval_examples = self.eval_examples if eval_examples is None else eval_examples

        compute_metrics = self.compute_metrics
        self.compute_metrics = None
        try:
            output = self.prediction_loop(
                eval_dataloader,
                description="Evaluation",
                prediction_loss_only=True if compute_metrics is None else None,
                ignore_keys=ignore_keys,
            )
        finally:
            self.compute_metrics = compute_metrics

        eval_dataset.set_format(type=eval_dataset.format["type"], columns=list(eval_dataset.features.keys()))

        if self.compute_metrics is not None:
            eval_preds = self._post_process_function(eval_examples, eval_dataset, output.predictions)
            metrics = self.compute_metrics(eval_preds)
            # For some reason the eval_loss is not returned in output's metrics
            # Work around since NotebookProgressCallback assumes eval_loss key exists
            metrics['eval_loss'] = 'No log'

            self.log(metrics)
        else:
            metrics = {}

        for key in list(metrics.keys()):
            if not key.startswith(f"eval_"):
                metrics[f"eval_{key}"] = metrics.pop(key)

        self.control = self.callback_handler.on_evaluate(self.args, self.state, self.control, metrics)
        return metrics

    def predict(self, test_dataset, test_examples, ignore_keys=None):
        test_dataloader = self.get_test_dataloader(test_dataset)
        compute_metrics = self.compute_metrics
        self.compute_metrics = None
        try:
            output = self.prediction_loop(
                test_dataloader,
                description="Evaluation",
                prediction_loss_only=True if compute_metrics is None else None,
                ignore_keys=ignore_keys,
            )
        finally:
            self.compute_metrics = compute_metrics

        if self.compute_metrics is None:
            return output

        test_dataset.set_format(type=test_dataset.format["type"], columns=list(test_dataset.features.keys()))
        eval_preds = self._post_process_function(test_examples, test_dataset, output.predictions)
        metrics = self.compute_metrics(eval_preds)

        return PredictionOutput(predictions=eval_preds.predictions, label_ids=eval_preds.label_ids, metrics=metrics)


    def _post_process_function(self, examples, features, predictions):
        predictions = self._postprocess_qa_predictions(
            examples=examples,
            features=features,
            predictions=predictions,
            version_2_with_negative=self.args.version_2_with_negative,
            n_best_size=self.args.n_best_size,
            max_answer_length=self.args.max_answer_length,
            null_score_diff_threshold=self.args.null_score_diff_threshold,
            output_dir=self.args.output_dir,
            is_world_process_zero=self.is_world_process_zero(),
        )
        if self.args.version_2_with_negative:
            formatted_predictions = [
                {"id": k, "prediction_text": v, "no_answer_probability": 0.0} for k, v in predictions.items()
            ]
        else:
            formatted_predictions = [{"id": k, "prediction_text": v} for k, v in predictions.items()]
        references = [{"id": ex["id"], "answers": ex['answers']} for ex in self.eval_examples]
        return EvalPrediction(predictions=formatted_predictions, label_ids=references)


    def _postprocess_qa_predictions(
        self,
        examples,
        features,
        predictions,
        version_2_with_negative= False,
        n_best_size = None,
        max_answer_length = None,
        null_score_diff_threshold = None,
        output_dir = None,
        prefix = None,
        is_world_process_zero = True,
    ):
        assert len(predictions) == 2, "`predictions` should be a tuple with two elements (start_logits, end_logits)."
        all_start_logits, all_end_logits = predictions
        assert len(predictions[0]) == len(features), f"Got {len(predictions[0])} predictions and {len(features)} features."

        example_id_to_index = {k: i for i, k in enumerate(examples["id"])}
        features_per_example = collections.defaultdict(list)
        for i, feature in enumerate(features):
            features_per_example[example_id_to_index[feature["example_id"]]].append(i)

        all_predictions = collections.OrderedDict()

        for example_index, example in enumerate(tqdm(examples)):
            feature_indices = features_per_example[example_index]
            min_null_prediction = None
            prelim_predictions = []

            for feature_index in feature_indices:
                start_logits = all_start_logits[feature_index]
                end_logits = all_end_logits[feature_index]
                offset_mapping = features[feature_index]["offset_mapping"]
                token_is_max_context = features[feature_index].get("token_is_max_context", None)
                feature_null_score = start_logits[0] + end_logits[0]
                if min_null_prediction is None or min_null_prediction["score"] > feature_null_score:
                    min_null_prediction = {
                        "offsets": (0, 0),
                        "score": feature_null_score,
                        "start_logit": start_logits[0],
                        "end_logit": end_logits[0],
                    }

                start_indexes = np.argsort(start_logits)[-1 : -self.args.n_best_size - 1 : -1].tolist()
                end_indexes = np.argsort(end_logits)[-1 : -self.args.n_best_size - 1 : -1].tolist()
                for start_index in start_indexes:
                    for end_index in end_indexes:
                        if (
                            start_index >= len(offset_mapping)
                            or end_index >= len(offset_mapping)
                            or offset_mapping[start_index] is None
                            or offset_mapping[end_index] is None
                        ):
                            continue
                        if end_index < start_index or end_index - start_index + 1 > self.args.max_answer_length:
                            continue
                        if token_is_max_context is not None and not token_is_max_context.get(str(start_index), False):
                            continue
                        prelim_predictions.append(
                            {
                                "offsets": (offset_mapping[start_index][0], offset_mapping[end_index][1]),
                                "score": start_logits[start_index] + end_logits[end_index],
                                "start_logit": start_logits[start_index],
                                "end_logit": end_logits[end_index],
                            }
                        )
            if self.args.version_2_with_negative:
                prelim_predictions.append(min_null_prediction)
                null_score = min_null_prediction["score"]

            predictions = sorted(prelim_predictions, key=lambda x: x["score"], reverse=True)[:self.args.n_best_size]
            if self.args.version_2_with_negative and not any(p["offsets"] == (0, 0) for p in predictions):
                predictions.append(min_null_prediction)

            context = example["context"]
            for pred in predictions:
                offsets = pred.pop("offsets")
                pred["text"] = context[offsets[0] : offsets[1]]

            if len(predictions) == 0 or (len(predictions) == 1 and predictions[0]["text"] == ""):
                predictions.insert(0, {"text": "empty", "start_logit": 0.0, "end_logit": 0.0, "score": 0.0})

            scores = np.array([pred.pop("score") for pred in predictions])
            exp_scores = np.exp(scores - np.max(scores))
            probs = exp_scores / exp_scores.sum()

            for prob, pred in zip(probs, predictions):
                pred["probability"] = prob

            if not self.args.version_2_with_negative:
                all_predictions[example["id"]] = predictions[0]["text"]
            else:
                i = 0
                while predictions[i]["text"] == "":
                    i += 1
                best_non_null_pred = predictions[i]

                score_diff = null_score - best_non_null_pred["start_logit"] - best_non_null_pred["end_logit"]
                if score_diff > self.args.null_score_diff_threshold:
                    all_predictions[example["id"]] = ""
                else:
                    all_predictions[example["id"]] = best_non_null_pred["text"]

        return all_predictions