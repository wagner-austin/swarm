# Capability-Based Worker Architecture

This document describes the future capability-based routing system for Swarm's AI task execution platform.

## Current State (As-Is)

Currently, tasks are routed to fixed queues based on task name patterns:

```python
# From celery_app.py
app.conf.task_routes = {
    "browser.*": {"queue": "browser"},
    "tankpit.*": {"queue": "tankpit"}, 
    "llm.*": {"queue": "llm"},
}
```

Workers consume from specific queues:
- Browser workers: Handle web scraping, screenshots, interactions
- Tankpit workers: (Currently unused)
- LLM workers: (Planned for local model inference)

## Future Vision (To-Be)

### Capability-Based Routing

Instead of hardcoded queue routing, workers will advertise their capabilities:

```python
# Example capability registry
WORKER_CAPABILITIES = {
    "search": ["web_search", "api_query", "database_lookup"],
    "analyze": ["summarize", "extract", "classify", "reason"],
    "browser": ["screenshot", "scrape", "click", "fill_form"],
    "code": ["read_file", "edit_file", "run_tests", "lint"],
    "document": ["generate_pdf", "create_report", "format_markdown"],
    "media": ["transcribe_audio", "extract_text_from_image", "generate_image"],
}
```

### Task Decomposition Example

User request: **"Research the environmental bill HR-1234 and prepare a summary"**

```yaml
Task Tree:
  root_task: "research_environmental_bill"
  subtasks:
    - task_id: "search_1"
      capability: "web_search"
      action: "Find bill HR-1234 on congress.gov"
      
    - task_id: "browser_1" 
      capability: "scrape"
      action: "Extract bill text and sponsors"
      depends_on: ["search_1"]
      
    - task_id: "search_2"
      capability: "web_search"  
      action: "Find news articles about HR-1234"
      
    - task_id: "analyze_1"
      capability: "summarize"
      action: "Summarize bill provisions"
      depends_on: ["browser_1"]
      
    - task_id: "analyze_2"
      capability: "extract"
      action: "Extract key stakeholder positions"
      depends_on: ["search_2"]
      
    - task_id: "document_1"
      capability: "create_report"
      action: "Generate final summary document"
      depends_on: ["analyze_1", "analyze_2"]
```

### Implementation Plan

#### Phase 1: Capability Registry (Current)
```python
# swarm/distributed/capabilities.py
from enum import Enum
from typing import Set, Dict

class Capability(Enum):
    # Web capabilities
    WEB_SEARCH = "web_search"
    SCREENSHOT = "screenshot"
    SCRAPE = "scrape"
    INTERACT = "interact"
    
    # Analysis capabilities  
    SUMMARIZE = "summarize"
    EXTRACT = "extract"
    CLASSIFY = "classify"
    REASON = "reason"
    
    # Code capabilities
    READ_CODE = "read_code"
    EDIT_CODE = "edit_code"
    RUN_TESTS = "run_tests"
    LINT_CODE = "lint_code"
    
    # Document capabilities
    GENERATE_PDF = "generate_pdf"
    CREATE_REPORT = "create_report"
    FORMAT_TEXT = "format_text"

# Worker capability mapping
WORKER_CAPABILITIES: Dict[str, Set[Capability]] = {
    "browser": {Capability.WEB_SEARCH, Capability.SCREENSHOT, Capability.SCRAPE, Capability.INTERACT},
    "llm": {Capability.SUMMARIZE, Capability.EXTRACT, Capability.CLASSIFY, Capability.REASON},
    "code": {Capability.READ_CODE, Capability.EDIT_CODE, Capability.RUN_TESTS, Capability.LINT_CODE},
    "document": {Capability.GENERATE_PDF, Capability.CREATE_REPORT, Capability.FORMAT_TEXT},
}
```

#### Phase 2: Dynamic Task Routing
```python
# swarm/distributed/task_router.py
class TaskRouter:
    def route_task(self, task: Task) -> str:
        """Route task to appropriate queue based on required capability."""
        capability = task.required_capability
        
        # Find queues that can handle this capability
        capable_queues = [
            queue for queue, caps in WORKER_CAPABILITIES.items()
            if capability in caps
        ]
        
        if not capable_queues:
            raise ValueError(f"No worker can handle capability: {capability}")
            
        # Load balance across capable queues
        return random.choice(capable_queues)
```

#### Phase 3: Task Decomposition Service
```python
# swarm/services/task_decomposer.py
class TaskDecomposer:
    """Breaks complex user requests into capability-based subtasks."""
    
    async def decompose(self, user_request: str) -> TaskTree:
        # Use LLM to understand request and required capabilities
        analysis = await self.llm.analyze_request(user_request)
        
        # Create task tree with dependencies
        root = Task(
            id=generate_id(),
            description=user_request,
            subtasks=[]
        )
        
        for step in analysis.steps:
            subtask = Task(
                id=generate_id(),
                capability=step.required_capability,
                action=step.action,
                depends_on=step.dependencies
            )
            root.subtasks.append(subtask)
            
        return TaskTree(root)
```

### Queue to Capability Mapping (Transition Period)

During the transition, we'll maintain backward compatibility:

| Current Queue | Maps to Capabilities | Worker Types |
|--------------|---------------------|--------------|
| `browser` | `web_search`, `screenshot`, `scrape`, `interact` | Playwright-based workers |
| `llm` | `summarize`, `extract`, `classify`, `reason` | GPU workers with local models |
| `tankpit` | `proxy`, `tunnel`, `vpn` | Network proxy workers |
| `analysis` | `data_processing`, `aggregation` | CPU-bound analysis |
| `document` | `pdf`, `report`, `format` | Document generation |

### Migration Strategy

1. **Phase 1** (Now): Document capabilities, keep existing queue structure
2. **Phase 2** (Month 1): Add capability metadata to tasks, dual routing
3. **Phase 3** (Month 2): Implement task decomposer with simple templates  
4. **Phase 4** (Month 3): Full capability-based routing with LLM decomposition

### Configuration Example

```yaml
# config/capabilities.yaml
worker_types:
  browser:
    capabilities:
      - web_search
      - screenshot  
      - scrape
      - interact
    resources:
      cpu: 2
      memory: 4Gi
      requires_display: true
      
  llm:
    capabilities:
      - summarize
      - extract
      - classify
      - reason
    resources:
      gpu: 1
      memory: 24Gi
      model_cache: /models
      
  code:
    capabilities:
      - read_code
      - edit_code
      - run_tests
      - lint_code
    resources:
      cpu: 4
      memory: 8Gi
      workspace_mount: /workspace
```

### Monitoring Capabilities

Add capability labels to metrics:

```python
# In celery task
@app.task(bind=True)
def process_with_capability(self, data, capability):
    # Track capability usage
    capability_counter.labels(
        capability=capability,
        queue=self.request.queue,
        worker=self.request.hostname
    ).inc()
```

Grafana query examples:
```promql
# Tasks by capability
sum by (capability) (rate(swarm_capability_tasks_total[5m]))

# Worker utilization by capability  
sum by (capability, worker) (swarm_capability_active_tasks)
```

## Benefits

1. **Flexibility**: New capabilities can be added without changing routing logic
2. **Efficiency**: Tasks routed to most appropriate workers
3. **Scalability**: Scale specific capabilities independently
4. **Clarity**: Clear mapping of what each worker can do
5. **Future-proof**: Ready for hundreds of specialized workers

## Next Steps

1. Create `swarm/distributed/capabilities.py` with capability enum
2. Add capability field to task metadata
3. Update celery routing to check capabilities
4. Build simple task decomposer for testing
5. Create capability-aware autoscaler logic