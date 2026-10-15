"""Deterministic neural layout, independent of Pygame and the engine."""

import heapq


def graph_layout(genome):
    nodes = {n[0]: n for n in genome["nodes"]}
    incoming = dict.fromkeys(nodes, 0)
    outgoing = {i: [] for i in nodes}
    depth = dict.fromkeys(nodes, 0)
    for source, target, _ in genome["connections"]:
        incoming[target] += 1
        outgoing[source].append(target)
    queue = [i for i in nodes if incoming[i] == 0]
    heapq.heapify(queue)
    visited = 0
    while queue:
        source = heapq.heappop(queue)
        visited += 1
        for target in outgoing[source]:
            depth[target] = max(depth[target], depth[source] + 1)
            incoming[target] -= 1
            if not incoming[target]:
                heapq.heappush(queue, target)
    if visited != len(nodes):
        raise ValueError("Cannot display a cyclic neural graph")
    last = max((d for i, d in depth.items() if nodes[i][1] != "output"), default=0) + 1
    for i in nodes:
        if nodes[i][1] == "output":
            depth[i] = last
    positions = {}
    for level in sorted(set(depth.values())):
        ids = sorted(i for i in nodes if depth[i] == level)
        for j, i in enumerate(ids):
            positions[i] = ((level + 0.4) / (last + 0.8), (j + 1) / (len(ids) + 1))
    return positions
