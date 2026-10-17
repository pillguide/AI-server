"""Extracted from model_b_refinement_eval and model_b_robust_eval (2026-10-10).

Preserves proposal-index scores, class-aware NMS and the existing review policy.
No dependencies on research code, dataset manifests or server-local paths.
"""
from collections import defaultdict
import hashlib
import json
import math


def iou_xyxy(a, b):
    intersection = max(0.0, min(a[2], b[2]) - max(a[0], b[0])) * max(
        0.0, min(a[3], b[3]) - max(a[1], b[1]))
    union = ((a[2] - a[0]) * (a[3] - a[1])
             + (b[2] - b[0]) * (b[3] - b[1]) - intersection)
    return intersection / union if union > 0 else 0.0


def annotate_candidates(predictions):
    parents = list(range(len(predictions)))

    def root(i):
        while parents[i] != i:
            parents[i] = parents[parents[i]]
            i = parents[i]
        return i

    for i, a in enumerate(predictions):
        for j in range(i):
            b = predictions[j]
            if a['class_id'] != b['class_id'] and iou_xyxy(a['bbox_xyxy'], b['bbox_xyxy']) >= .5:
                parents[root(i)] = root(j)
    groups = defaultdict(list)
    for i in range(len(predictions)):
        groups[root(i)].append(i)
    conflicts = {i: f'conflict_{min(indices)}' for indices in groups.values()
                 if len(indices) > 1 for i in indices}
    for i, p in enumerate(predictions):
        scores = p['class_scores']
        if len(scores) != 150 or any(not math.isfinite(s) or not 0 <= s <= 1 for s in scores):
            raise ValueError('Expected 150 finite class scores per retained proposal')
        ranking = sorted(range(150), key=lambda cid: (-scores[cid], cid))[:3]
        if p['class_id'] != ranking[0] or not math.isclose(p['confidence'], scores[ranking[0]], abs_tol=1e-7):
            raise ValueError('NMS proposal index does not reproduce raw class/confidence')
        p['candidates'] = [{'class_id': cid, 'score': scores[cid], 'source': 'detector_sigmoid'} for cid in ranking]
        reasons = []
        if scores[ranking[0]] < .9:
            reasons.append('top1_below_0.9')
        if scores[ranking[0]] - scores[ranking[1]] < .2:
            reasons.append('margin_below_0.2')
        if i in conflicts:
            reasons.append('different_class_overlap')
        p['conflict_group_id'] = conflicts.get(i)
        p['review_reasons'] = reasons
        p['needs_review'] = bool(reasons)
    return predictions


def proposal_predictor_class():
    from ultralytics.models.yolo.detect.predict import DetectionPredictor
    from ultralytics.utils.nms import non_max_suppression

    class ProposalPredictor(DetectionPredictor):
        def postprocess(self, preds, img, orig_imgs, **kwargs):
            raw = preds[0] if isinstance(preds, (tuple, list)) else preds
            if raw.shape[1] != 154 or getattr(self.model, 'end2end', False):
                raise ValueError('Expected YOLO11 150-class BCN raw output')
            class_scores = raw[:, 4:154, :].clone()
            detections, indexes = non_max_suppression(
                raw, self.args.conf, self.args.iou, classes=self.args.classes,
                agnostic=False, max_det=self.args.max_det, return_idxs=True)
            results = self.construct_results(detections, img, orig_imgs)
            for bi, result in enumerate(results):
                boxes = result.boxes
                scores = class_scores[bi, :, indexes[bi].long().view(-1)].T.cpu().tolist()
                result.proposal_predictions = annotate_candidates([
                    {'class_id': int(cid), 'confidence': float(conf), 'bbox_xyxy': list(map(float, box)),
                     'proposal_index': int(index), 'class_scores': score}
                    for cid, conf, box, index, score in zip(
                        boxes.cls.cpu().tolist(), boxes.conf.cpu().tolist(),
                        boxes.xyxyn.cpu().tolist(), indexes[bi].cpu().view(-1).tolist(), scores, strict=True)])
            return results
    return ProposalPredictor


class InferenceEngine:
    def __init__(self, settings):
        import torch
        from ultralytics import YOLO
        self.device = settings.device
        if self.device != 'cpu' and not torch.cuda.is_available():
            raise RuntimeError('CUDA unavailable; install the CUDA PyTorch build and NVIDIA driver. CPU is opt-in only.')
        weights = settings.root / 'model/final_H.pt'
        if not weights.is_file():
            raise FileNotFoundError('model/final_H.pt is missing')
        mapping = settings.root / 'model/classes.json'
        self.options = settings.inference
        with weights.open('rb') as handle:
            self.model_sha256 = hashlib.file_digest(handle, 'sha256').hexdigest()
        with mapping.open('rb') as handle:
            self.mapping_sha256 = hashlib.file_digest(handle, 'sha256').hexdigest()
        if self.model_sha256 != self.options['model_sha256']:
            raise ValueError('Model hash differs from the selected H checkpoint')
        if self.mapping_sha256 != self.options['mapping_sha256']:
            raise ValueError('Class mapping hash differs from the packaged H mapping')
        classes = json.loads(mapping.read_text(encoding='utf-8'))
        expected = {int(row['class_id']): str(row['product_code']) for row in classes}
        if len(classes) != 150 or sorted(expected) != list(range(150)):
            raise ValueError('Expected a unique mapping of class IDs 0 through 149')
        self.model = YOLO(str(weights), task='detect')
        if {int(cid): str(name) for cid, name in self.model.names.items()} != expected:
            raise ValueError('Checkpoint product-code mapping differs from classes.json')
        self.model.to(self.device)
        self.model.model.float()
        if self.options['review'] != {'top1_min': .9, 'margin_min': .2, 'conflict_iou': .5, 'candidate_count': 3}:
            raise ValueError('Review policy differs from the fixed H output contract')
        self.predictor_class = proposal_predictor_class()
        self.ready = False

    def predict(self, image):
        options = {key: self.options[key] for key in (
            'imgsz', 'conf', 'iou', 'max_det', 'rect', 'agnostic_nms', 'augment', 'half', 'batch')}
        options.update(device='0' if self.device == 'cuda:0' else 'cpu',
                       save=False, verbose=False, stream=True)
        if not self.ready:
            options['predictor'] = self.predictor_class
        results = list(self.model.predict(image, **options))
        self.ready = True
        if len(results) != 1:
            raise RuntimeError('Expected exactly one image result')
        keys = ('class_id', 'confidence', 'bbox_xyxy', 'candidates',
                'needs_review', 'review_reasons', 'conflict_group_id')
        return [{key: p[key] for key in keys} for p in results[0].proposal_predictions]
