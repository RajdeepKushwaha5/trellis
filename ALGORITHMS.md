# Why Trellis uses these graph operations

This is an explanation of the current implementation, not a claim that every named graph algorithm is used. The runtime queries are in [backend/reasoning.py](backend/reasoning.py) and [backend/tutor/graphq.py](backend/tutor/graphq.py).

## First understand the edge direction

`(goal)-[:REQUIRES]->(foundation)` means the goal depends on that foundation. Follow outgoing REQUIRES edges to find earlier foundations. Follow the relationship backwards to find concepts a foundation supports. Hard prerequisites influence readiness; BENEFITS_FROM edges are optional context.

## Current decisions

| Operation | Implementation | Why this choice fits | What it does not establish |
|---|---|---|---|
| Complete prerequisite closure | `REQUIRES*0..` with `DISTINCT` | Finds every hard prerequisite across multiple branches; zero hops includes the goal. DISTINCT prevents a concept reached by several paths from being counted several times. | The source prerequisites are not independently verified educational truths. |
| Explanation witness | `shortestPath((goal)-[:REQUIRES*]->(foundation))` | Shows one compact, minimum-hop connection explaining relevance. Paths are reversed for foundation-to-goal display. | A shortest explanation is not a complete curriculum or an optimal learning plan. Multiple shortest witnesses may exist. |
| Reverse branch coverage | Count distinct route concepts that can reach each candidate foundation | Gives a goal-specific measure of how much of the selected route depends on it. Better aligned with a chosen goal than global popularity. The current zero-hop pattern counts the foundation itself too. | High coverage does not prove this learner needs that concept, or that teaching it will fix other skills. |
| Candidate ranking | Cypher `ORDER BY` over eligibility, suspected difficulty, distance, inferred-only support and coverage | Makes an explicit product policy inspectable and reproducible. Evidence and permissions constrain what the model can choose. | ORDER BY is a ranking policy, not an independent graph algorithm or an optimal planner. Some input flags are assembled by controller code. |
| Mistake-to-strategy matching | `Observation-[:SUGGESTS]->DifficultyHypothesis<-[:ADDRESSES]-TeachingStrategy` and `Activity-[:USES_STRATEGY]->TeachingStrategy` | Returns strategies actually connected to recorded evidence and this activity. | Relationships are authored prototype mappings, not learned causal findings or diagnoses. |
| Distinguishing checks | `Diagnostic-[:DISTINGUISHES]->DifficultyHypothesis`, gated on an ambiguous hypothesis | Offers a bounded additional check only when the response leaves competing explanations. The task engine prefers items exposing more of the relevant error codes. | This is a coverage heuristic, not Bayesian diagnosis or optimal information gain. Item selection within a pool runs in Python. |
| Evidence streak and transfer eligibility | Queries join TaskIssue, Observation and Representation; controller applies support rule v2 | Distinguishes practice from unhinted checks and requires evidence across representations. | The rule is a product policy, not a validated mastery threshold. |

**Import validation is separate:** Kahn's topological cycle check runs in Python before curriculum import. It ensures acyclicity; it is not a FalkorDB runtime algorithm. GRAPH.COPY, constraints, full-text indexes and GRAPH.EXPLAIN are database features, not additional graph algorithms.

## Should we replace closure traversal with BFS?

BFS is a legitimate alternative when exploring prerequisites layer by layer. It is not automatically an improvement.

A local read-only comparison on all 1,590 goals found identical reachable concept sets after adding the source node and accounting for leaf goals. The installed BFS procedure returned rows for 1,375 non-leaf goals; the existing zero-length closure includes all 1,590 goals directly. In five warm bulk runs per query:

| Query | Median server time |
|---|---:|
| Current variable-length closure | 121.5 ms |
| BFS procedure per goal in a bulk query | 853.3 ms |

See [the actual samples and query](evidence/algorithm-comparison.json). These are noisy local measurements for this bulk workload, not general FalkorDB performance claims or individual-agent latency. They do not justify replacing the current implementation. In this installed version a depth of zero returned no results; the audit used an explicit bound of 1,590, sufficient for any simple path in this validated 1,590-node DAG. BFS is audited here, not used by the runtime.

## Other algorithms considered

- **PageRank:** measures network influence. A globally influential concept can be irrelevant to the chosen goal or already supported for this learner. Keep goal-scoped coverage and evidence-driven readiness for this decision.
- **Betweenness centrality:** useful for locating structural bridges, potentially a curriculum-authoring view. A bridge is not necessarily the learner's missing foundation, so it should not decide tutoring priority by itself.
- **Weighted shortest paths / Dijkstra:** potentially useful once validated lesson durations or costs exist. We do not currently have those weights. Also, taking one cheapest path can omit other required branches: prerequisites are not generally interchangeable routes.
- **Topological ordering:** useful for an entire prerequisite-respecting lesson sequence. Trellis currently chooses the next diagnostic and can intentionally probe an uncertain concept, so strict ordering should not replace investigation.
- **Community detection:** potentially useful for curriculum exploration or content organization, not evidence that a specific learner needs a particular lesson.

## Most useful future improvement

Investigate **unresolved coverage**: rank how many still-uncertain concepts on this learner's goal route depend on a candidate, rather than counting supported and uncertain concepts equally. Combine it with the existing readiness and suspected-difficulty constraints. Test cases must establish that it avoids redundant checks without abandoning required foundations before changing the policy.

For ambiguous mistakes, a later extension could rank probes by how well they separate competing explanations. Without calibrated response probabilities, call this a discrimination heuristic, not expected information gain. The existing finite item pools and independent grader remain important.

## Explanation for a judge

"The graph tells Scout which foundations lead to the goal and how much of the route depends on them. A shortest path explains why a foundation matters; it does not claim to be the whole learning plan. The learner's recorded response connects to possible explanations, eligible teaching strategies and distinguishing checks. The controller bounds the actions, the model selects a permitted action, and code grades and records the result."

## Official references

- [FalkorDB algorithms overview](https://docs.falkordb.com/algorithms/)
- [BFS procedure](https://docs.falkordb.com/algorithms/bfs)
- [Cypher functions, including shortestPath](https://docs.falkordb.com/cypher/functions)
- [PageRank](https://docs.falkordb.com/algorithms/pagerank)
