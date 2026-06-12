"""Git-history replay benchmark for dorian (H1 backed-claim ratio, H2 alarm quality).

Modules: `replay` (walk real or scripted history, score baseline vs dorian
alarms), `ground_truth` (heuristic GT + human labeling queue), `metrics`
(precision/recall/FP-reduction with bootstrap CIs and the gate verdict).
Plain stdlib; config is JSON (`bench/repos.json`) to keep the kernel zero-dep.
"""
