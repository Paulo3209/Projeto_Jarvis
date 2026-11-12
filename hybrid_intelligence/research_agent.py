"""
Research Agent - Autonomous research and information gathering.
Web search, document analysis, fact verification, synthesis.
"""
from __future__ import annotations
import asyncio
import logging
import json
import time
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional, Callable
from pathlib import Path

logger = logging.getLogger(__name__)


class ResearchStatus(Enum):
    """Research task status."""
    PENDING = "pending"
    PLANNING = "planning"
    SEARCHING = "searching"
    ANALYZING = "analyzing"
    SYNTHESIZING = "synthesizing"
    COMPLETED = "completed"
    FAILED = "failed"


class SourceType(Enum):
    """Information source types."""
    WEB = "web"
    ACADEMIC = "academic"
    NEWS = "news"
    DOCUMENT = "document"
    CODE = "code"
    API = "api"
    DATABASE = "database"
    INTERNAL = "internal"


@dataclass
class ResearchSource:
    """Information source."""
    source_id: str
    source_type: SourceType
    title: str
    url: str = ""
    content: str = ""
    snippet: str = ""
    credibility: float = 0.5  # 0-1
    relevance: float = 0.5
    metadata: Dict = field(default_factory=dict)
    retrieved_at: datetime = field(default_factory=datetime.now)


@dataclass
class ResearchTask:
    """Research task definition."""
    task_id: str
    query: str
    objectives: List[str] = field(default_factory=list)
    constraints: List[str] = field(default_factory=list)
    source_types: List[SourceType] = field(default_factory=lambda: [SourceType.WEB])
    max_sources: int = 20
    depth: int = 2  # 1=shallow, 2=normal, 3=deep
    require_citations: bool = True
    language: str = "pt-BR"
    output_format: str = "report"  # report, summary, bullets, json
    created_at: datetime = field(default_factory=datetime.now)


@dataclass
class ResearchResult:
    """Research task result."""
    task_id: str
    status: ResearchStatus
    query: str
    summary: str = ""
    detailed_findings: str = ""
    sources: List[ResearchSource] = field(default_factory=list)
    key_facts: List[str] = field(default_factory=list)
    citations: List[Dict] = field(default_factory=list)
    confidence: float = 0.0
    duration: float = 0.0
    completed_at: Optional[datetime] = None
    error: str = ""

    def to_dict(self) -> Dict:
        return {
            "task_id": self.task_id,
            "status": self.status.value,
            "query": self.query,
            "summary": self.summary,
            "detailed_findings": self.detailed_findings,
            "sources": [
                {
                    "source_id": s.source_id,
                    "type": s.source_type.value,
                    "title": s.title,
                    "url": s.url,
                    "credibility": s.credibility,
                    "relevance": s.relevance,
                }
                for s in self.sources
            ],
            "key_facts": self.key_facts,
            "citations": self.citations,
            "confidence": self.confidence,
            "duration": self.duration,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "error": self.error,
        }


class ResearchAgent:
    """
    Autonomous research agent.
    Plans, searches, analyzes, and synthesizes information.
    """

    def __init__(self):
        self._search_providers: Dict[SourceType, Callable] = {}
        self._running_tasks: Dict[str, ResearchTask] = {}
        self._results: Dict[str, ResearchResult] = {}
        self._register_default_providers()

    def _register_default_providers(self) -> None:
        """Register default search providers."""
        self._search_providers = {
            SourceType.WEB: self._search_web,
            SourceType.NEWS: self._search_news,
            SourceType.ACADEMIC: self._search_academic,
            SourceType.DOCUMENT: self._search_documents,
            SourceType.CODE: self._search_code,
        }

    def register_provider(self, source_type: SourceType, provider: Callable) -> None:
        """Register custom search provider."""
        self._search_providers[source_type] = provider

    async def research(self, task: ResearchTask) -> ResearchResult:
        """Execute research task."""
        start_time = time.time()
        task_id = task.task_id

        result = ResearchResult(
            task_id=task_id,
            status=ResearchStatus.PLANNING,
            query=task.query,
        )

        self._running_tasks[task_id] = task
        self._results[task_id] = result

        try:
            # Phase 1: Planning
            result.status = ResearchStatus.PLANNING
            plan = await self._plan_research(task)

            # Phase 2: Search
            result.status = ResearchStatus.SEARCHING
            sources = await self._execute_search(task, plan)

            # Phase 3: Analysis
            result.status = ResearchStatus.ANALYZING
            analyzed = await self._analyze_sources(sources, task)

            # Phase 4: Synthesis
            result.status = ResearchStatus.SYNTHESIZING
            synthesis = await self._synthesize_findings(analyzed, task)

            # Finalize
            result.status = ResearchStatus.COMPLETED
            result.summary = synthesis.get("summary", "")
            result.detailed_findings = synthesis.get("detailed", "")
            result.sources = sources
            result.key_facts = synthesis.get("key_facts", [])
            result.citations = synthesis.get("citations", [])
            result.confidence = synthesis.get("confidence", 0.0)
            result.completed_at = datetime.now()

        except Exception as e:
            result.status = ResearchStatus.FAILED
            result.error = str(e)
            logger.error(f"Research failed: {e}")

        finally:
            result.duration = time.time() - start_time
            self._running_tasks.pop(task_id, None)

        return result

    async def _plan_research(self, task: ResearchTask) -> Dict:
        """Plan research strategy."""
        # Simple planning - in real implementation would use LLM
        sub_queries = [task.query]

        if task.objectives:
            sub_queries.extend(task.objectives)

        # Add variations for depth
        if task.depth >= 2:
            sub_queries.append(f"{task.query} detailed analysis")
            sub_queries.append(f"{task.query} examples")
        if task.depth >= 3:
            sub_queries.append(f"{task.query} technical details")
            sub_queries.append(f"{task.query} best practices")

        return {
            "sub_queries": sub_queries[:5],
            "source_priority": task.source_types,
            "max_per_source": task.max_sources // len(task.source_types) if task.source_types else 5,
        }

    async def _execute_search(self, task: ResearchTask, plan: Dict) -> List[ResearchSource]:
        """Execute search across sources."""
        all_sources = []

        for source_type in task.source_types:
            provider = self._search_providers.get(source_type)
            if not provider:
                continue

            max_sources = plan.get("max_per_source", 5)
            sub_queries = plan.get("sub_queries", [task.query])

            for query in sub_queries:
                try:
                    sources = await provider(query, max_sources)
                    all_sources.extend(sources)
                except Exception as e:
                    logger.error(f"Search error for {source_type}: {e}")

        # Deduplicate by URL
        seen_urls = set()
        unique_sources = []
        for src in all_sources:
            if src.url and src.url in seen_urls:
                continue
            if src.url:
                seen_urls.add(src.url)
            unique_sources.append(src)

        # Sort by relevance + credibility
        unique_sources.sort(key=lambda s: (s.relevance + s.credibility) / 2, reverse=True)

        return unique_sources[:task.max_sources]

    async def _search_web(self, query: str, max_results: int) -> List[ResearchSource]:
        """Web search (placeholder - would use actual search API)."""
        # This would integrate with actual search APIs (Google, Bing, DuckDuckGo, etc.)
        # For now, return mock sources
        return [
            ResearchSource(
                source_id=f"web_{hash(query + str(i))}",
                source_type=SourceType.WEB,
                title=f"Result {i+1} for: {query}",
                url=f"https://example.com/result{i}",
                snippet=f"Snippet for {query}...",
                credibility=0.7,
                relevance=0.8,
            )
            for i in range(min(max_results, 3))
        ]

    async def _search_news(self, query: str, max_results: int) -> List[ResearchSource]:
        """News search."""
        return [
            ResearchSource(
                source_id=f"news_{hash(query + str(i))}",
                source_type=SourceType.NEWS,
                title=f"News {i+1}: {query}",
                url=f"https://news.example.com/article{i}",
                snippet=f"Recent news about {query}...",
                credibility=0.8,
                relevance=0.7,
            )
            for i in range(min(max_results, 2))
        ]

    async def _search_academic(self, query: str, max_results: int) -> List[ResearchSource]:
        """Academic search (Google Scholar, Semantic Scholar, etc.)."""
        return [
            ResearchSource(
                source_id=f"academic_{hash(query + str(i))}",
                source_type=SourceType.ACADEMIC,
                title=f"Paper {i+1}: {query}",
                url=f"https://scholar.example.com/paper{i}",
                snippet=f"Academic paper on {query}...",
                credibility=0.95,
                relevance=0.8,
                metadata={"venue": "Conference/Journal", "year": 2024},
            )
            for i in range(min(max_results, 2))
        ]

    async def _search_documents(self, query: str, max_results: int) -> List[ResearchSource]:
        """Search internal documents."""
        from hybrid_intelligence.semantic_memory import get_semantic_memory, MemoryQuery, MemoryType

        try:
            memory = get_semantic_memory()
            results = await memory.search(query, max_results, MemoryType.DOCUMENT)

            sources = []
            for result in results:
                sources.append(ResearchSource(
                    source_id=f"doc_{result.entry.id}",
                    source_type=SourceType.DOCUMENT,
                    title=result.entry.metadata.get("title", "Document"),
                    url=f"memory://{result.entry.id}",
                    content=result.entry.content[:2000],
                    snippet=result.entry.content[:300],
                    credibility=0.9,
                    relevance=result.similarity,
                    metadata=result.entry.metadata,
                ))
            return sources
        except Exception:
            return []

    async def _search_code(self, query: str, max_results: int) -> List[ResearchSource]:
        """Search code repositories."""
        return [
            ResearchSource(
                source_id=f"code_{hash(query + str(i))}",
                source_type=SourceType.CODE,
                title=f"Code example {i+1}: {query}",
                url=f"https://github.com/example/repo{i}",
                snippet=f"Code snippet for {query}...",
                credibility=0.7,
                relevance=0.6,
            )
            for i in range(min(max_results, 2))
        ]

    async def _analyze_sources(self, sources: List[ResearchSource], task: ResearchTask) -> List[Dict]:
        """Analyze and extract information from sources."""
        analyzed = []

        for source in sources:
            analysis = {
                "source": source,
                "key_points": [],
                "entities": [],
                "claims": [],
                "data": {},
            }

            # In real implementation, would use LLM to analyze
            # For now, extract from snippet/content
            text = source.content or source.snippet

            # Simple extraction
            sentences = text.split(". ")
            analysis["key_points"] = [s.strip() for s in sentences if len(s) > 20][:5]

            analyzed.append(analysis)

        return analyzed

    async def _synthesize_findings(self, analyzed: List[Dict], task: ResearchTask) -> Dict:
        """Synthesize findings into coherent output."""
        all_points = []
        all_sources = []

        for a in analyzed:
            all_points.extend(a["key_points"])
            all_sources.append(a["source"])

        # Deduplicate points
        unique_points = list(dict.fromkeys(all_points))

        # Generate summary
        if task.output_format == "summary":
            summary = f"Research on '{task.query}' found {len(unique_points)} key points from {len(all_sources)} sources."
        elif task.output_format == "bullets":
            summary = "\n".join([f"• {p}" for p in unique_points[:10]])
        else:
            summary = f"## Research Summary: {task.query}\n\n"
            summary += f"Analyzed {len(all_sources)} sources.\n\n"
            summary += "### Key Findings:\n"
            for i, point in enumerate(unique_points[:10], 1):
                summary += f"{i}. {point}\n"

        # Citations
        citations = []
        for src in all_sources:
            citations.append({
                "title": src.title,
                "url": src.url,
                "type": src.source_type.value,
            })

        return {
            "summary": summary,
            "detailed": f"Detailed analysis of {len(unique_points)} points...",
            "key_facts": unique_points[:10],
            "citations": citations,
            "confidence": min(0.9, len(all_sources) * 0.15 + 0.3),
        }

    def get_task_status(self, task_id: str) -> Optional[ResearchStatus]:
        """Get task status."""
        if task_id in self._results:
            return self._results[task_id].status
        if task_id in self._running_tasks:
            return ResearchStatus.PLANNING
        return None

    def get_result(self, task_id: str) -> Optional[ResearchResult]:
        """Get research result."""
        return self._results.get(task_id)

    def list_tasks(self) -> List[Dict]:
        """List all tasks."""
        return [
            {
                "task_id": r.task_id,
                "query": r.query,
                "status": r.status.value,
                "duration": r.duration,
                "completed_at": r.completed_at.isoformat() if r.completed_at else None,
            }
            for r in self._results.values()
        ]


# Global instance
_research_agent: Optional[ResearchAgent] = None


def get_research_agent() -> ResearchAgent:
    """Get global research agent."""
    global _research_agent
    if _research_agent is None:
        _research_agent = ResearchAgent()
    return _research_agent


async def quick_research(
    query: str,
    max_sources: int = 10,
    depth: int = 2,
) -> ResearchResult:
    """Quick research convenience function."""
    agent = get_research_agent()
    task = ResearchTask(
        task_id=f"research_{int(time.time())}",
        query=query,
        max_sources=max_sources,
        depth=depth,
    )
    return await agent.research(task)