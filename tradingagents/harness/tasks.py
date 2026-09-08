"""Run playbook prompts against an LLM with structured JSON output.

``LLMCallable`` is any ``callable(prompt_text) -> str``. That keeps the runner
independent of LangChain so it can be unit-tested with a stub and used with
``tradingagents.llm_clients`` in production via ``llm_from_config``.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Iterable, Mapping

from .prompts import PlaybookPrompt, get_prompt, list_prompts, render_prompt


LLMCallable = Callable[[str], str]

SYSTEM_PREAMBLE = (
    "당신은 한국 주식(코스피/코스닥) 리서치 하네스의 분석 에이전트입니다. "
    "제공된 데이터와 도구 결과에 근거해서만 판단하고, 근거 없는 가격이나 수치를 만들어내지 마세요. "
    "출력은 반드시 아래 JSON 스키마를 따르는 단일 JSON 객체여야 하며, 다른 텍스트를 붙이지 마세요. "
    "투자 조언이 아니라 리서치 결과이며 실제 주문과 연결되지 않습니다."
)


@dataclass(frozen=True)
class HarnessTask:
    prompt: PlaybookPrompt
    values: dict[str, Any]
    context: dict[str, Any] = field(default_factory=dict)

    @property
    def id(self) -> str:
        return self.prompt.id

    def build_prompt(self) -> str:
        question = render_prompt(self.prompt, self.values)
        sections = [SYSTEM_PREAMBLE, "", f"## 과제 {self.prompt.order}. {self.prompt.title}", question, ""]
        context = {key: value for key, value in self.context.items() if value not in (None, "", [], {})}
        if context:
            sections.append("## 제공 데이터")
            sections.append(json.dumps(_compact(context), ensure_ascii=False, indent=2, default=str))
            sections.append("")
        sections.append("## 출력 JSON 스키마")
        sections.append(json.dumps(self.prompt.schema, ensure_ascii=False, indent=2))
        sections.append("")
        sections.append("JSON만 출력하세요.")
        return "\n".join(sections)


@dataclass(frozen=True)
class HarnessTaskResult:
    task_id: str
    title: str
    status: str  # ok | parse_error | llm_error
    prompt_text: str
    raw_output: str
    data: dict[str, Any]
    error: str | None = None
    started_at: str = ""
    finished_at: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "title": self.title,
            "status": self.status,
            "data": self.data,
            "error": self.error,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "raw_output": self.raw_output,
        }


def run_task(task: HarnessTask, llm: LLMCallable) -> HarnessTaskResult:
    prompt_text = task.build_prompt()
    started = _now()
    try:
        raw = llm(prompt_text)
    except Exception as exc:
        return HarnessTaskResult(
            task_id=task.id,
            title=task.prompt.title,
            status="llm_error",
            prompt_text=prompt_text,
            raw_output="",
            data={},
            error=f"{exc.__class__.__name__}: {exc}",
            started_at=started,
            finished_at=_now(),
        )
    raw_text = raw if isinstance(raw, str) else getattr(raw, "content", str(raw))
    data, error = parse_json_output(raw_text)
    return HarnessTaskResult(
        task_id=task.id,
        title=task.prompt.title,
        status="ok" if error is None else "parse_error",
        prompt_text=prompt_text,
        raw_output=raw_text,
        data=data,
        error=error,
        started_at=started,
        finished_at=_now(),
    )


def run_playbook(
    llm: LLMCallable,
    *,
    values: Mapping[str, Any],
    context: Mapping[str, Any] | None = None,
    prompt_ids: Iterable[str] | None = None,
    extended: bool = True,
) -> list[HarnessTaskResult]:
    """Run selected (or all) playbook prompts in order.

    ``context`` is a mapping keyed by the prompt ``context_keys`` (chart,
    fundamentals, news, screener, forecast, risk_metrics, ...). Each task only
    receives the slices it declares so prompts stay focused and cheap.
    ``extended=False`` limits the default set to the operator's ten prompts.
    """

    selected = [get_prompt(prompt_id) for prompt_id in prompt_ids] if prompt_ids else list_prompts(extended=extended)
    selected.sort(key=lambda prompt: prompt.order)
    context = dict(context or {})
    results: list[HarnessTaskResult] = []
    for prompt in selected:
        task_context = {key: context[key] for key in prompt.context_keys if key in context}
        if results:
            task_context["previous_conclusions"] = {r.task_id: r.data.get("summary") for r in results if r.status == "ok"}
        results.append(run_task(HarnessTask(prompt=prompt, values=dict(values), context=task_context), llm))
    return results


def parse_json_output(text: str) -> tuple[dict[str, Any], str | None]:
    """Extract the first JSON object from an LLM response (tolerates code fences)."""

    if not text or not text.strip():
        return {}, "empty response"
    candidate = text.strip()
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", candidate, re.DOTALL)
    if fenced:
        candidate = fenced.group(1)
    else:
        start = candidate.find("{")
        end = candidate.rfind("}")
        if start != -1 and end != -1 and end > start:
            candidate = candidate[start : end + 1]
    try:
        parsed = json.loads(candidate)
    except json.JSONDecodeError as exc:
        return {}, f"invalid JSON: {exc.msg} at {exc.pos}"
    if not isinstance(parsed, dict):
        return {}, "JSON root must be an object"
    return parsed, None


def llm_from_config(config: Mapping[str, Any] | None = None, *, deep: bool = False) -> LLMCallable:
    """Adapt ``tradingagents.llm_clients`` to the plain ``callable(str) -> str`` shape."""

    from tradingagents.default_config import DEFAULT_CONFIG
    from tradingagents.llm_clients import create_llm_client

    cfg = dict(DEFAULT_CONFIG)
    cfg.update(config or {})
    client = create_llm_client(
        provider=cfg["llm_provider"],
        model=cfg["deep_think_llm"] if deep else cfg["quick_think_llm"],
        base_url=cfg.get("backend_url"),
    )
    llm = client.get_llm()

    def _call(prompt: str) -> str:
        response = llm.invoke(prompt)
        content = getattr(response, "content", response)
        if isinstance(content, list):
            content = "".join(part.get("text", "") if isinstance(part, dict) else str(part) for part in content)
        return str(content)

    return _call


def _compact(value: Any, *, max_list: int = 60) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _compact(item, max_list=max_list) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        items = list(value)
        if len(items) > max_list:
            items = items[-max_list:]
        return [_compact(item, max_list=max_list) for item in items]
    if hasattr(value, "as_dict"):
        return _compact(value.as_dict(), max_list=max_list)
    return value


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()
