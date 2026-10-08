from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.taxonomy import Topic


@dataclass(frozen=True)
class InitialTopic:
    slug: str
    name: str
    parent_slug: str | None
    sort_order: int


INITIAL_TOPICS = (
    InitialTopic("llm-context", "LLM 与上下文", None, 10),
    InitialTopic("llm-basics", "LLM 基础", "llm-context", 10),
    InitialTopic("prompt", "Prompt", "llm-context", 20),
    InitialTopic("structured-output", "Structured Output", "llm-context", 30),
    InitialTopic("context-engineering", "Context Engineering", "llm-context", 40),
    InitialTopic("tool-protocol", "工具与协议", None, 20),
    InitialTopic("function-calling-tool-use", "Function Calling / Tool Use", "tool-protocol", 10),
    InitialTopic("mcp", "MCP", "tool-protocol", 20),
    InitialTopic("retrieval-memory", "检索与记忆", None, 30),
    InitialTopic("rag", "RAG", "retrieval-memory", 10),
    InitialTopic("memory", "Memory", "retrieval-memory", 20),
    InitialTopic("agent-framework-control", "Agent 框架与控制流", None, 40),
    InitialTopic("langchain", "LangChain", "agent-framework-control", 10),
    InitialTopic("langgraph", "LangGraph", "agent-framework-control", 20),
    InitialTopic("multi-agent", "Multi-Agent", "agent-framework-control", 30),
    InitialTopic("agent-design-patterns", "Agent 设计模式", None, 50),
    InitialTopic("agent-pattern-react", "ReAct", "agent-design-patterns", 10),
    InitialTopic("agent-pattern-plan-execute", "Plan-and-Execute", "agent-design-patterns", 20),
    InitialTopic("agent-pattern-reflection", "Reflection", "agent-design-patterns", 30),
    InitialTopic("agent-pattern-router", "Router", "agent-design-patterns", 40),
    InitialTopic("agent-pattern-supervisor", "Supervisor", "agent-design-patterns", 50),
    InitialTopic("workflow-vs-agent", "Workflow vs Agent", "agent-design-patterns", 60),
    InitialTopic("human-in-the-loop", "Human-in-the-loop", "agent-design-patterns", 70),
    InitialTopic("quality-safety", "质量与安全", None, 60),
    InitialTopic("agent-evaluation", "Agent Evaluation", "quality-safety", 10),
    InitialTopic("observability", "Observability", "quality-safety", 20),
    InitialTopic("agent-security", "Agent Security", "quality-safety", 30),
    InitialTopic("engineering", "工程基础", None, 70),
    InitialTopic("deployment", "部署", "engineering", 10),
    InitialTopic("python-backend", "Python/后端", "engineering", 20),
    InitialTopic("experience", "经历与实践", None, 80),
    InitialTopic("project-practice", "项目实践", "experience", 10),
)


def seed_initial_topics(session: Session) -> None:
    existing = {topic.slug: topic for topic in session.scalars(select(Topic)).all()}
    for entry in INITIAL_TOPICS:
        if entry.slug in existing:
            continue
        parent = existing.get(entry.parent_slug) if entry.parent_slug else None
        topic = Topic(
            track_key="agent_development",
            parent=parent,
            slug=entry.slug,
            name=entry.name,
            sort_order=entry.sort_order,
            is_active=True,
        )
        session.add(topic)
        session.flush()
        existing[entry.slug] = topic
