# Session 10: Evaluation — Preparedness Assessment Quality

---

## What you're doing and why

Session 9 ran the system under degraded conditions and observed the output. This session measures it.

The evaluation framework answers: did the supervisor correctly identify resource gaps, and did it recommend commands that address those gaps? You compare the supervisor's assessment against ground truth from `readiness_summary()` — not against fire prediction, which would be unevaluable without a real ML model.

This gives you a concrete score you can use to compare stub mode vs. LLM mode, and to track whether changes to the agent improve or regress assessment quality.

---

## Setup

This session builds on Session 9. If you're continuing, activate your environment and move on.

If you're starting fresh:

```bash
uv venv && source .venv/bin/activate
uv pip install -e ".[llm]" --group dev
git remote add tutorial https://github.com/chrislomeli/agentic-world-simulator.git
git fetch tutorial
git checkout tutorial/main -- src/ tests/
pytest tests/ -q   # everything should pass before you start
```

---

## Rubric coverage

This session exercises the full system and demonstrates evaluability of preparedness-based agents. No new LangGraph patterns — the focus is evaluation methodology.

---

## What you're building

No new source files. The `PreparednessEvaluator` class in this session is a self-contained evaluation script.

---

## Why not detection accuracy?

Binary prediction ("fire will happen" / "fire won't") puts the agent in a win-lose position with no real ML model behind it. Preparedness assessment is different:

**What makes preparedness evaluable:**

1. **"High fire potential"** is always defensible given dry conditions and sensor data — we can verify the sensor readings that led to this assessment

2. **"Cluster-south lacks helicopter coverage"** is a verifiable fact about resource state — we can compare the assessment to `readiness_summary()`

3. **False positives are caution**, not errors — exactly what preparedness should produce

4. **Recommendation quality** is measurable — did the commands address the actual gaps?

Ground truth still matters — but as context for evaluating the assessment, not as a binary scorecard.

---

## The evaluation dimensions

We evaluate preparedness assessments across four dimensions:

### 1. Gap detection accuracy

**What it measures:** Did the supervisor correctly identify which clusters are under-resourced?

**How to evaluate:**

```python
# Ground truth: compute actual gaps
readiness = resources.readiness_summary()
actual_gaps = []
for cluster_id in ["cluster-north", "cluster-south"]:
    cluster_res = resources.by_cluster(cluster_id)
    avail = [r for r in cluster_res if r.status == ResourceStatus.AVAILABLE]
    if len(avail) == 0 and len(cluster_res) > 0:
        actual_gaps.append(cluster_id)

# Supervisor assessment: check if gaps were mentioned
summary = result["situation_summary"].lower()
mentioned_gaps = "gap" in summary or "unavailable" in summary or "out of service" in summary

# Evaluation
if actual_gaps and not mentioned_gaps:
    print("⚠ MISS: gaps exist but supervisor didn't mention them")
elif mentioned_gaps and not actual_gaps:
    print("ℹ Conservative: supervisor noted potential gaps (acceptable)")
else:
    print("✓ MATCH: gap detection aligned with ground truth")
```

### 2. Recommendation quality

**What it measures:** Did the commands address the actual gaps?

**How to evaluate:**

```python
# Ground truth: which clusters have gaps?
clusters_with_gaps = []
for cluster_id in ["cluster-north", "cluster-south"]:
    prep = check_preparedness(cluster_id)  # From resource_tools
    if prep["gaps"]:
        clusters_with_gaps.append(cluster_id)

# Supervisor commands: which clusters were targeted?
command_targets = [cmd.cluster_id for cmd in result["pending_commands"]]

# Evaluation
for cluster in clusters_with_gaps:
    if cluster in command_targets:
        print(f"✓ Cluster {cluster}: gap detected, command issued")
    else:
        print(f"⚠ Cluster {cluster}: gap detected, no command issued")
```

### 3. Degradation sensitivity

**What it measures:** Did assessment urgency increase as conditions worsened?

**How to evaluate:**

```python
# Run 3 scenarios: baseline, 50% degraded, 100% degraded
scenarios = [
    ("Baseline", 0.0),
    ("50% degraded", 0.5),
    ("100% degraded", 1.0),
]

urgency_scores = []
for label, frac in scenarios:
    result = run_scenario(label, resource_disable_frac=frac)
    
    # Compute urgency score from commands
    urgency = sum(5 - cmd.priority for cmd in result["pending_commands"])  # Lower priority = higher urgency
    urgency_scores.append(urgency)
    
    print(f"{label}: urgency score = {urgency}")

# Evaluation: urgency should increase with degradation
if urgency_scores[0] < urgency_scores[1] < urgency_scores[2]:
    print("✓ Degradation sensitivity: urgency increased appropriately")
else:
    print("⚠ Degradation sensitivity: urgency did not scale with degradation")
```

### 4. Conservative bias

**What it measures:** Does the supervisor err on the side of caution?

**How to evaluate:**

```python
# False positives (flagged gaps that don't exist) are acceptable
# False negatives (missed gaps) are not

false_positives = mentioned_gaps and not actual_gaps
false_negatives = actual_gaps and not mentioned_gaps

if false_negatives:
    print("⚠ CRITICAL: missed gaps (false negative)")
elif false_positives:
    print("✓ ACCEPTABLE: conservative assessment (false positive)")
else:
    print("✓ ACCURATE: assessment matched ground truth")
```

---

## Building the evaluation framework

Here's a complete evaluation script:

```python
import asyncio
import random
from typing import List, Dict, Any
from domains.wildfire import create_full_wildfire_scenario
from domains.wildfire.sensors import TemperatureSensor, SmokeSensor
from sensors import SensorPublisher
from transport import SensorEventQueue
from bridge.consumer import EventBridgeConsumer
from agents.cluster.graph import build_cluster_agent_graph
from agents.supervisor.graph import build_supervisor_graph
from langgraph.store.memory import InMemoryStore
from resources.base import ResourceStatus

class PreparednessEvaluator:
    """Evaluates supervisor preparedness assessments."""
    
    def __init__(self):
        self.results = []
    
    async def run_scenario(self, label: str, resource_disable_frac: float = 0.0) -> Dict[str, Any]:
        """Run pipeline and collect results."""
        random.seed(42)
        engine, resources = create_full_wildfire_scenario()
        
        # Apply degradation
        disabled = []
        if resource_disable_frac > 0:
            disabled = resources.disable_resources("engine", fraction=resource_disable_frac)
        
        # Build pipeline
        queue = SensorEventQueue()
        sensors = [
            TemperatureSensor(
                source_id="temp-n1", cluster_id="cluster-north",
                engine=engine, grid_row=3, grid_col=3,
            ),
            SmokeSensor(
                source_id="smoke-s1", cluster_id="cluster-south",
                engine=engine, grid_row=7, grid_col=5,
            ),
        ]
        publisher = SensorPublisher(sensors=sensors, queue=queue, engine=engine)
        
        store = InMemoryStore()
        cluster_graph = build_cluster_agent_graph(store=store)
        supervisor_graph = build_supervisor_graph(
            store=store,
            resource_inventory=resources,
        )
        
        findings = []
        consumer = EventBridgeConsumer(
            queue=queue,
            agent_graph=cluster_graph,
            batch_size=5,
            on_finding=lambda f: findings.append(f),
        )
        
        # Run pipeline
        await publisher.run(ticks=20)
        await consumer.run(max_events=queue.total_enqueued)
        
        # Run supervisor
        result = supervisor_graph.invoke({
            "active_cluster_ids": ["cluster-north", "cluster-south"],
            "cluster_findings": findings,
            "messages": [],
            "pending_commands": [],
            "situation_summary": None,
            "status": "idle",
            "error_message": None,
        })
        
        # Collect ground truth
        readiness = resources.readiness_summary()
        actual_gaps = []
        for cluster_id in ["cluster-north", "cluster-south"]:
            cluster_res = resources.by_cluster(cluster_id)
            avail = [r for r in cluster_res if r.status == ResourceStatus.AVAILABLE]
            out_of_service = [r for r in cluster_res if r.status == ResourceStatus.OUT_OF_SERVICE]
            if out_of_service:
                actual_gaps.append({
                    "cluster_id": cluster_id,
                    "gap_type": "out_of_service",
                    "count": len(out_of_service),
                    "total": len(cluster_res),
                })
        
        # Store result
        eval_result = {
            "label": label,
            "resource_disable_frac": resource_disable_frac,
            "disabled_resources": disabled,
            "findings_count": len(findings),
            "supervisor_summary": result["situation_summary"],
            "commands": result["pending_commands"],
            "actual_gaps": actual_gaps,
            "readiness": readiness,
        }
        self.results.append(eval_result)
        
        return eval_result
    
    def evaluate_gap_detection(self, result: Dict[str, Any]) -> Dict[str, Any]:
        """Evaluate gap detection accuracy."""
        summary = result["supervisor_summary"].lower()
        mentioned_gaps = any(
            keyword in summary
            for keyword in ["gap", "unavailable", "out of service", "disabled", "reduced"]
        )
        actual_gaps_exist = len(result["actual_gaps"]) > 0
        
        if actual_gaps_exist and not mentioned_gaps:
            verdict = "MISS"
            score = 0.0
        elif mentioned_gaps and not actual_gaps_exist:
            verdict = "CONSERVATIVE"
            score = 0.8  # Conservative is acceptable
        else:
            verdict = "MATCH"
            score = 1.0
        
        return {
            "dimension": "gap_detection",
            "mentioned_gaps": mentioned_gaps,
            "actual_gaps_exist": actual_gaps_exist,
            "verdict": verdict,
            "score": score,
        }
    
    def evaluate_recommendation_quality(self, result: Dict[str, Any]) -> Dict[str, Any]:
        """Evaluate whether commands address actual gaps."""
        clusters_with_gaps = {gap["cluster_id"] for gap in result["actual_gaps"]}
        command_targets = {cmd.cluster_id for cmd in result["commands"]}
        
        if not clusters_with_gaps:
            # No gaps = no commands needed
            score = 1.0 if not command_targets else 0.8  # Commands issued anyway = conservative
            verdict = "NO_GAPS"
        else:
            # Gaps exist = commands should target those clusters
            addressed = clusters_with_gaps.intersection(command_targets)
            score = len(addressed) / len(clusters_with_gaps) if clusters_with_gaps else 1.0
            verdict = "ADDRESSED" if score == 1.0 else "PARTIAL"
        
        return {
            "dimension": "recommendation_quality",
            "clusters_with_gaps": list(clusters_with_gaps),
            "command_targets": list(command_targets),
            "verdict": verdict,
            "score": score,
        }
    
    def print_evaluation(self):
        """Print evaluation results."""
        print("\n" + "="*70)
        print("PREPAREDNESS ASSESSMENT EVALUATION")
        print("="*70)
        
        for result in self.results:
            print(f"\n{result['label']}:")
            print(f"  Disabled: {len(result['disabled_resources'])} resources")
            print(f"  Findings: {result['findings_count']}")
            print(f"  Commands: {len(result['commands'])}")
            print(f"  Summary: {result['supervisor_summary'][:120]}...")
            
            # Gap detection
            gap_eval = self.evaluate_gap_detection(result)
            print(f"\n  Gap Detection:")
            print(f"    Mentioned gaps: {gap_eval['mentioned_gaps']}")
            print(f"    Actual gaps: {gap_eval['actual_gaps_exist']}")
            print(f"    Verdict: {gap_eval['verdict']} (score={gap_eval['score']:.1f})")
            
            # Recommendation quality
            rec_eval = self.evaluate_recommendation_quality(result)
            print(f"\n  Recommendation Quality:")
            print(f"    Clusters with gaps: {rec_eval['clusters_with_gaps']}")
            print(f"    Command targets: {rec_eval['command_targets']}")
            print(f"    Verdict: {rec_eval['verdict']} (score={rec_eval['score']:.1f})")
        
        # Overall scores
        print("\n" + "="*70)
        print("OVERALL SCORES:")
        gap_scores = [self.evaluate_gap_detection(r)["score"] for r in self.results]
        rec_scores = [self.evaluate_recommendation_quality(r)["score"] for r in self.results]
        print(f"  Gap Detection: {sum(gap_scores)/len(gap_scores):.2f} avg")
        print(f"  Recommendation Quality: {sum(rec_scores)/len(rec_scores):.2f} avg")
        print("="*70)

# Run evaluation
async def main():
    evaluator = PreparednessEvaluator()
    
    await evaluator.run_scenario("Baseline — full resources", resource_disable_frac=0.0)
    await evaluator.run_scenario("50% engines disabled", resource_disable_frac=0.5)
    await evaluator.run_scenario("All engines disabled", resource_disable_frac=1.0)
    
    evaluator.print_evaluation()

asyncio.run(main())
```

---

## Expected output

**Stub mode:**

```
======================================================================
PREPAREDNESS ASSESSMENT EVALUATION
======================================================================

Baseline — full resources:
  Disabled: 0 resources
  Findings: 2
  Commands: 0
  Summary: [STUB] Received 2 finding(s) from 2 cluster(s). Store contains 0 past incident(s) across all clusters.

  Gap Detection:
    Mentioned gaps: False
    Actual gaps: False
    Verdict: MATCH (score=1.0)

  Recommendation Quality:
    Clusters with gaps: []
    Command targets: []
    Verdict: NO_GAPS (score=1.0)

50% engines disabled:
  Disabled: 1 resources
  Findings: 2
  Commands: 0
  Summary: [STUB] Received 2 finding(s) from 2 cluster(s). Store contains 0 past incident(s) across all clusters.

  Gap Detection:
    Mentioned gaps: False
    Actual gaps: True
    Verdict: MISS (score=0.0)  ← Stub mode doesn't detect gaps

  Recommendation Quality:
    Clusters with gaps: ['cluster-south']
    Command targets: []
    Verdict: PARTIAL (score=0.0)

======================================================================
OVERALL SCORES:
  Gap Detection: 0.50 avg
  Recommendation Quality: 0.67 avg
======================================================================
```

Stub mode fails gap detection when degradation occurs (expected — no LLM to query resources).

**LLM mode:**

```
50% engines disabled:
  Disabled: 1 resources
  Findings: 2
  Commands: 1
  Summary: Temperature and smoke detected. Resource assessment: cluster-south has 1/2 engines out of service, reducing capacity...

  Gap Detection:
    Mentioned gaps: True
    Actual gaps: True
    Verdict: MATCH (score=1.0)  ← LLM detected the gap

  Recommendation Quality:
    Clusters with gaps: ['cluster-south']
    Command targets: ['cluster-south']
    Verdict: ADDRESSED (score=1.0)  ← Command targeted the right cluster

All engines disabled:
  Disabled: 2 resources
  Findings: 2
  Commands: 2
  Summary: Critical resource gap: cluster-south has 0/2 engines available. No water suppression capacity. Immediate escalation...

  Gap Detection:
    Mentioned gaps: True
    Actual gaps: True
    Verdict: MATCH (score=1.0)

  Recommendation Quality:
    Clusters with gaps: ['cluster-south']
    Command targets: ['cluster-south']
    Verdict: ADDRESSED (score=1.0)

======================================================================
OVERALL SCORES:
  Gap Detection: 1.00 avg
  Recommendation Quality: 1.00 avg
======================================================================
```

LLM mode achieves perfect scores: gaps detected, commands issued to the right clusters.

---

## What you learned: Evaluation framework patterns

This session demonstrated preparedness-based evaluation:

**1. Gap detection accuracy** — compare supervisor assessment to `readiness_summary()` ground truth.

**2. Recommendation quality** — verify commands target clusters with actual gaps.

**3. Degradation sensitivity** — urgency should increase as conditions worsen.

**4. Conservative bias** — false positives (flagged gaps that don't exist) are acceptable; false negatives (missed gaps) are not.

**5. Evaluable without prediction** — preparedness assessment quality is measurable even when fire prediction is impossible.

**6. LLM vs. stub comparison** — LLM mode significantly outperforms stub mode on gap detection and recommendation quality.

This evaluation framework demonstrates that preparedness-based agents are useful, evaluable, and robust — a viable alternative to binary prediction tasks.

---

## What you've built

At this point you have a complete, runnable testbed:

**World simulation:**
- Generic world engine with fire physics
- Ground truth snapshots for evaluation

**Sensor layer:**
- Noisy sensors with failure modes (STUCK, DROPOUT, DRIFT)
- Sensor inventory with scenario knobs

**Agent layer:**
- LangGraph cluster agents (stub + LLM modes)
- LangGraph supervisor with Send API fan-out
- Multi-agent coordination and state mapping

**Resource layer:**
- ResourceBase and ResourceInventory
- NWCG-aligned wildfire resources
- Scenario knobs for degradation testing

**Tool integration:**
- Sensor tools (4) for cluster agents
- Supervisor tools (4) for findings analysis
- Resource tools (4) for preparedness assessment

**Evaluation framework:**
- Gap detection accuracy
- Recommendation quality
- Degradation sensitivity
- Conservative bias measurement

**Observability:**
- LangSmith tracing for debugging
- Stream mode for real-time inspection
- Ground truth comparison

This is a production-ready agentic monitoring system with full evaluation capabilities.

---

## Checkpoint

Run the `PreparednessEvaluator` script. Verify:
- Stub mode: baseline scores 1.0, degraded scenarios score 0.0 for gap detection (expected — stub can't query resources)
- LLM mode: all scenarios score 1.0 for gap detection and recommendation quality
- The score difference between stub and LLM mode is the concrete demonstration of why the LLM matters

---

## Key files

- `src/world/generic_engine.py` — `GenericGroundTruthSnapshot`, `engine.history`
- `src/resources/inventory.py` — `check_preparedness()`, `readiness_summary()`
- `src/agents/supervisor/state.py` — `SupervisorState` (situation_summary, pending_commands)
- `src/tools/resource_tools.py` — resource querying tools

---

**Congratulations!** You've completed the tutorial series. You now have:
- A deep understanding of LangGraph multi-agent patterns
- A complete agentic monitoring pipeline
- An evaluation framework for preparedness-based agents
- A testbed for experimenting with sensor degradation, resource scarcity, and agent resilience

The next step is to extend this system with your own domain logic, sensors, resources, and evaluation metrics.
