from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass, field


@dataclass(slots=True)
class GraphRecallResult:
    ppr_scores: dict[int, float] = field(default_factory=dict)
    jaccard_scores: dict[int, float] = field(default_factory=dict)
    node_count: int = 0
    edge_count: int = 0


def personalized_pagerank(
    edges: list[tuple[int, int]],
    *,
    seed_weights: dict[int, float],
    alpha: float = 0.2,
    iterations: int = 25,
    min_seed_hits: int = 2,
) -> dict[int, float]:
    """Pure-dict PPR over the artist follow graph (Twitter WTF / Pinterest Pixie).

    v = alpha * seed + (1 - alpha) * M @ v, power iteration. seed_weights lets
    high-bookmark follows pull harder. Pixie-style multi-hit: only nodes reached
    from >= min_seed_hits distinct seeds survive (kills one-seed-neighborhood
    noise). Thousands of nodes → milliseconds; no scipy needed.
    """
    if not edges or not seed_weights:
        return {}
    out_neighbors: dict[int, list[int]] = defaultdict(list)
    for follower, followee in edges:
        out_neighbors[int(follower)].append(int(followee))

    total_seed = sum(max(0.0, w) for w in seed_weights.values()) or 1.0
    seed_vector = {int(node): max(0.0, w) / total_seed for node, w in seed_weights.items() if w > 0}
    if not seed_vector:
        return {}

    rank = dict(seed_vector)
    damping = 1.0 - float(alpha)
    for _ in range(max(1, int(iterations))):
        spread: dict[int, float] = defaultdict(float)
        for node, mass in rank.items():
            targets = out_neighbors.get(node)
            if not targets:
                continue
            share = (mass * damping) / len(targets)
            for target in targets:
                spread[target] += share
        rank = {node: seed_vector.get(node, 0.0) * float(alpha) for node in set(seed_vector) | set(spread)}
        for node, mass in spread.items():
            rank[node] = rank.get(node, 0.0) + mass

    if min_seed_hits > 1:
        # Multi-hit filter: count distinct seeds whose 1-hop neighborhood reaches the node.
        hit_counts: dict[int, int] = defaultdict(int)
        for seed in seed_vector:
            reached = set(out_neighbors.get(seed, ()))
            for node in reached:
                hit_counts[node] += 1
        rank = {
            node: score
            for node, score in rank.items()
            if node in seed_vector or hit_counts.get(node, 0) >= int(min_seed_hits)
        }
    return rank


def cofollow_jaccard(
    edges: list[tuple[int, int]],
    *,
    followed_ids: set[int],
    min_shared: int = 2,
) -> dict[int, float]:
    """Max Jaccard between a candidate's follower set and each followed artist's.

    Both sets live in the observed graph (followers drawn from expanded seeds),
    so the overlap is computed on comparable footing. min_shared kills
    single-cofollower coincidences.
    """
    if not edges:
        return {}
    followers_of: dict[int, set[int]] = defaultdict(set)
    for follower, followee in edges:
        followers_of[int(followee)].add(int(follower))

    followed_follower_sets = {
        artist_id: followers_of[artist_id]
        for artist_id in followed_ids
        if followers_of.get(artist_id)
    }
    if not followed_follower_sets:
        return {}

    scores: dict[int, float] = {}
    for candidate, candidate_followers in followers_of.items():
        if candidate in followed_ids or len(candidate_followers) < int(min_shared):
            continue
        best = 0.0
        for follower_set in followed_follower_sets.values():
            shared = len(candidate_followers & follower_set)
            if shared < int(min_shared):
                continue
            union = len(candidate_followers | follower_set)
            if union:
                best = max(best, shared / union)
        if best > 0:
            scores[candidate] = best
    return scores


def graph_recall(
    edges: list[tuple[int, int]],
    *,
    followed_ids: set[int],
    seed_quality: dict[int, float] | None = None,
    max_candidates: int = 300,
    ppr_iterations: int = 25,
) -> GraphRecallResult:
    """Combined graph recall over recorded artist→artist follow edges.

    Seeds = followed artists present in the graph, weighted by log1p(quality)
    (local max bookmarks) when available. Returns normalized PPR scores for
    non-followed nodes plus co-follow Jaccard scores.
    """
    followed = {int(a) for a in followed_ids}
    graph_nodes = {follower for follower, _ in edges} | {followee for _, followee in edges}
    seeds = followed & graph_nodes
    result = GraphRecallResult(node_count=len(graph_nodes), edge_count=len(edges))
    if not seeds:
        return result

    quality = seed_quality or {}
    seed_weights = {node: 1.0 + math.log1p(max(0.0, float(quality.get(node, 0.0)))) for node in seeds}
    ppr = personalized_pagerank(
        edges,
        seed_weights=seed_weights,
        iterations=ppr_iterations,
    )
    candidate_ppr = {node: score for node, score in ppr.items() if node not in followed}
    if candidate_ppr:
        top = sorted(candidate_ppr.items(), key=lambda kv: -kv[1])[: max(1, int(max_candidates))]
        peak = top[0][1] or 1.0
        result.ppr_scores = {node: score / peak for node, score in top}

    result.jaccard_scores = cofollow_jaccard(edges, followed_ids=followed)
    return result
