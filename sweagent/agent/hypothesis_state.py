from __future__ import annotations

import json
import re
import textwrap
import time
from dataclasses import dataclass, field
from typing import Any, Iterable


@dataclass
class StackFrame:
    index: int
    function: str | None = None
    file: str | None = None
    line: int | None = None
    raw: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "index": self.index,
            "function": self.function or "",
            "file": self.file or "",
            "line": self.line or "",
            "raw": self.raw,
        }


@dataclass
class SanitizerReport:
    error_type: str = ""
    summary: str = ""
    crash_location: str | None = None
    stack: list[StackFrame] = field(default_factory=list)

    def to_prompt_dict(self) -> dict[str, Any]:
        return {
            "error_type": self.error_type or "unknown-error",
            "summary": self.summary or "",
            "crash_location": self.crash_location or "",
            "call_stack": [frame.to_dict() for frame in self.stack[:8]],
        }


class SanitizerReportAnalyzer:
    """Very small sanitizer parser - extracts error type and first few frames."""

    _ERROR_RE = re.compile(r"==\d+==ERROR: [A-Za-z]+Sanitizer: (?P<error>.+)")
    _FRAME_RE = re.compile(
        r"#(?P<idx>\d+)\s+0x[0-9a-fA-F]+\s+in\s+(?P<function>[^\s]+)(?:\s+\((?P<location>[^)]+)\))?"
    )
    _LOCATION_RE = re.compile(r"(?P<file>[^:]+):(?P<line>\d+)")

    def __init__(self, max_lines: int = 160):
        self.max_lines = max_lines

    def analyze(self, report_text: str) -> SanitizerReport:
        lines = report_text.splitlines()[: self.max_lines]
        joined = "\n".join(lines)

        error_type = ""
        crash_location = None
        stack: list[StackFrame] = []

        error_match = self._ERROR_RE.search(joined)
        if error_match:
            error_type = error_match.group("error").strip()

        for line in lines:
            frame_match = self._FRAME_RE.search(line)
            if not frame_match:
                continue
            idx = int(frame_match.group("idx"))
            fn = frame_match.group("function")
            location = frame_match.group("location") or ""
            file_name = None
            line_no = None
            loc_match = self._LOCATION_RE.search(location)
            if loc_match:
                file_name = loc_match.group("file")
                line_no = int(loc_match.group("line"))
                crash_location = f"{file_name}:{line_no}"

            stack.append(
                StackFrame(
                    index=idx,
                    function=fn,
                    file=file_name,
                    line=line_no,
                    raw=line.strip(),
                )
            )

        summary = ""
        if error_type:
            summary = f"Sanitizer reports {error_type}"
            if crash_location:
                summary += f" at {crash_location}"

        return SanitizerReport(
            error_type=error_type,
            summary=summary,
            crash_location=crash_location,
            stack=stack,
        )


@dataclass
class HypothesisEntry:
    hypothesis_id: str
    description: str
    status: str = "active"
    priority: int = 0
    open_questions: list[str] = field(default_factory=list)
    suggested_steps: list[str] = field(default_factory=list)
    evidence: list[str] = field(default_factory=list)
    keyframes: dict[str, str] = field(default_factory=dict)
    verification_plan: list[str] = field(default_factory=list)

    def to_prompt_block(self) -> str:
        lines = [f"[{self.hypothesis_id}] ({self.status}) {self.description}"]
        if self.suggested_steps:
            lines.append("  Steps:")
            lines.extend(f"    - {step}" for step in self.suggested_steps)
        if self.open_questions:
            lines.append("  Open Questions:")
            lines.extend(f"    - {q}" for q in self.open_questions)
        if self.evidence:
            lines.append("  Evidence:")
            lines.extend(f"    - {ev}" for ev in self.evidence[-3:])
        if self.keyframes:
            lines.append("  Keyframes:")
            for name, desc in self.keyframes.items():
                lines.append(f"    - {name}: {desc}")
        if self.verification_plan:
            lines.append("  Verification plan:")
            lines.extend(f"    - {step}" for step in self.verification_plan)
        return "\n".join(lines)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.hypothesis_id,
            "description": self.description,
            "status": self.status,
            "priority": self.priority,
            "open_questions": self.open_questions,
            "suggested_steps": self.suggested_steps,
            "evidence": self.evidence,
            "keyframes": self.keyframes,
            "verification_plan": self.verification_plan,
        }


class HypothesisState:
    """Lightweight in-memory tracker for hypothesis-driven exploration."""

    def __init__(self, report: SanitizerReport, history_limit: int = 50):
        self.report = report
        self.hypotheses: dict[str, HypothesisEntry] = {}
        self.active_id = ""
        self._counter = 1
        self.history_limit = max(history_limit, 1)
        self.update_log: list[dict[str, Any]] = []
        self.last_update_step: int = -1
        self._create_primary_hypothesis()

    def _create_primary_hypothesis(self) -> None:
        description = self.report.summary or "Investigate sanitizer crash."
        suggestion = []
        if self.report.crash_location:
            suggestion.append(f"Inspect code near {self.report.crash_location}")
        if self.report.stack:
            top_frame = self.report.stack[0]
            if top_frame.function:
                suggestion.append(f"Trace control flow into {top_frame.function} to locate unsafe operations")
        entry = HypothesisEntry(
            hypothesis_id="H0_primary",
            description=description,
            status="active",
            priority=0,
            suggested_steps=suggestion,
            open_questions=[f"Why does {self.report.error_type or 'the sanitizer'} trigger here?"],
        )
        self.hypotheses[entry.hypothesis_id] = entry
        self.active_id = entry.hypothesis_id

    def _allocate_id(self) -> str:
        new_id = f"H{self._counter}"
        self._counter += 1
        return new_id

    def allocate_id(self) -> str:
        return self._allocate_id()

    def set_active(self, hypothesis_id: str) -> None:
        if hypothesis_id not in self.hypotheses:
            raise KeyError(f"Hypothesis '{hypothesis_id}' does not exist.")
        self.active_id = hypothesis_id
        for hyp_id, entry in self.hypotheses.items():
            if hyp_id == hypothesis_id and entry.status == "pending":
                entry.status = "active"
            elif hyp_id != hypothesis_id and entry.status == "active":
                entry.status = "pending"

    def apply_update_from_json(self, raw_payload: str, *, step_index: int | None = None) -> str:
        payload = self._loads_payload(raw_payload)
        return self.apply_update(payload, step_index=step_index, raw_payload=raw_payload)

    def apply_update(self, payload: dict[str, Any], *, step_index: int | None = None, raw_payload: str | None = None) -> str:
        if not isinstance(payload, dict):
            raise ValueError("Hypothesis update payload must be a JSON object.")

        target_id = payload.get("hypothesis_id") or self.active_id
        if not target_id:
            raise ValueError("No hypothesis_id provided and no active hypothesis available.")

        entry = self.hypotheses.get(target_id)
        created = []

        if entry is None:
            entry = HypothesisEntry(
                hypothesis_id=target_id,
                description=payload.get("description", "New hypothesis"),
                status="pending",
            )
            self.hypotheses[target_id] = entry
            created.append(target_id)

        if "description" in payload:
            entry.description = payload["description"]
        if "status" in payload:
            entry.status = payload["status"]
        if "priority" in payload:
            entry.priority = int(payload["priority"])
        if "keyframes" in payload and isinstance(payload["keyframes"], dict):
            entry.keyframes = {str(k): str(v) for k, v in payload["keyframes"].items()}
        if "verification_plan" in payload:
            entry.verification_plan = [str(item) for item in self._as_iterable(payload.get("verification_plan"))]

        for key, container in (
            ("add_open_questions", entry.open_questions),
            ("add_suggested_steps", entry.suggested_steps),
            ("add_evidence", entry.evidence),
        ):
            for item in self._as_iterable(payload.get(key)):
                if item not in container:
                    container.append(item)

        for key, container in (
            ("resolve_open_questions", entry.open_questions),
            ("drop_suggested_steps", entry.suggested_steps),
        ):
            for item in self._as_iterable(payload.get(key)):
                if item in container:
                    container.remove(item)

        for note in self._as_iterable(payload.get("notes")):
            entry.evidence.append(note)

        new_hypotheses = []
        for new_entry in self._as_iterable(payload.get("new_hypotheses")):
            if not isinstance(new_entry, dict):
                continue
            hyp_id = new_entry.get("id") or self._allocate_id()
            description = new_entry.get("description") or "Follow-up hypothesis"
            hyp = HypothesisEntry(
                hypothesis_id=hyp_id,
                description=description,
                status=new_entry.get("status", "pending"),
                priority=int(new_entry.get("priority", len(self.hypotheses))),
                open_questions=list(new_entry.get("open_questions", [])),
                suggested_steps=list(new_entry.get("suggested_steps", [])),
                keyframes={str(k): str(v) for k, v in new_entry.get("keyframes", {}).items()} if isinstance(new_entry.get("keyframes"), dict) else {},
                verification_plan=[str(item) for item in self._as_iterable(new_entry.get("verification_plan"))],
            )
            self.hypotheses[hyp_id] = hyp
            new_hypotheses.append(hyp_id)

        activate_id = payload.get("activate") or payload.get("switch_to") or payload.get("set_active")
        if activate_id:
            if activate_id not in self.hypotheses:
                raise KeyError(f"Hypothesis '{activate_id}' does not exist.")
            self.set_active(activate_id)
        elif payload.get("found_contradiction") and entry.status != "refuted":
            entry.status = "refuted"
            fallback = self._find_next_pending(exclude={entry.hypothesis_id})
            if fallback:
                self.set_active(fallback)

        if payload.get("found_support") and entry.status == "pending":
            entry.status = "active"

        summary_lines = [f"Updated hypothesis {target_id} ({entry.status})."]
        if created:
            summary_lines.append(f"Created placeholder hypothesis {', '.join(created)}.")
        if new_hypotheses:
            summary_lines.append(f"Registered new hypotheses: {', '.join(new_hypotheses)}.")
        if activate_id:
            summary_lines.append(f"Activated hypothesis {self.active_id}.")
        elif self.active_id != target_id:
            summary_lines.append(f"Active hypothesis remains {self.active_id}.")
        if entry.keyframes:
            keyframe_preview = ", ".join(f"{k}:{v}" for k, v in list(entry.keyframes.items())[:4])
            summary_lines.append(f"Keyframes -> {keyframe_preview}")
        if entry.verification_plan:
            plan_preview = ", ".join(entry.verification_plan[:3])
            summary_lines.append(f"Verification plan steps -> {plan_preview}")
        if entry.open_questions:
            recent_questions = ", ".join(entry.open_questions[-3:])
            summary_lines.append(
                f"Open questions ({len(entry.open_questions)} total): {recent_questions}"
            )
        if entry.suggested_steps:
            summary_lines.append(f"Suggested next steps ({len(entry.suggested_steps)} total).")

        summary = "\n".join(summary_lines)
        self._record_update(
            step_index=step_index,
            summary=summary,
            payload=payload,
            raw_payload=raw_payload,
            active_id=self.active_id,
        )
        return summary

    def _find_next_pending(self, exclude: set[str] | None = None) -> str | None:
        exclude = exclude or set()
        pending = sorted(
            (hyp for hyp in self.hypotheses.values() if hyp.status in {"pending", "active"} and hyp.hypothesis_id not in exclude),
            key=lambda hyp: (hyp.priority, hyp.hypothesis_id),
        )
        for hyp in pending:
            return hyp.hypothesis_id
        return None

    def build_prompt_strings(self) -> dict[str, str]:
        current = self.hypotheses.get(self.active_id)
        current_block = current.to_prompt_block() if current else "No active hypothesis."

        board = "\n".join(
            hyp.to_prompt_block()
            for hyp in sorted(self.hypotheses.values(), key=lambda h: (h.priority, h.hypothesis_id))
        )
        sanitizer_block = self._format_sanitizer_summary()
        return {
            "hypothesis_current_block": current_block,
            "hypothesis_board": board,
            "sanitizer_context": sanitizer_block,
        }

    def to_extra_fields(self) -> dict[str, Any]:
        return {
            "hypothesis_state": {
                "active_id": self.active_id,
                "hypotheses": {hid: hyp.to_dict() for hid, hyp in self.hypotheses.items()},
                "update_log": self.update_log[-self.history_limit :],
                "last_update_step": self.last_update_step,
            },
            **self.build_prompt_strings(),
            "sanitizer_summary": self.report.to_prompt_dict(),
        }

    @staticmethod
    def _loads_payload(raw: str) -> dict[str, Any]:
        cleaned = raw.strip()
        if cleaned.startswith(("'", '"')) and cleaned.endswith(cleaned[0]):
            cleaned = cleaned[1:-1]
        cleaned = cleaned.strip()
        if cleaned.startswith("<<"):
            lines = cleaned.splitlines()
            sentinel = None
            if lines:
                first_line = lines[0]
                match = re.match(r"<<\s*'?(?P<end>[^']+)'?", first_line)
                if match:
                    sentinel = match.group("end").strip()
            body = lines[1:] if len(lines) > 1 else []
            if sentinel and body and body[-1].strip() == sentinel:
                body = body[:-1]
            cleaned = "\n".join(body).strip()
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Failed to parse hypothesis_update payload as JSON: {exc}") from exc

    @staticmethod
    def _as_iterable(values: Any) -> Iterable[str]:
        if not values:
            return []
        if isinstance(values, str):
            return [values]
        return [str(item) for item in values if item]

    def _format_sanitizer_summary(self) -> str:
        report = self.report.to_prompt_dict()
        header = report["summary"] or f"Sanitizer: {report['error_type']}"
        frames = []
        for frame in report["call_stack"]:
            loc = frame["raw"] or f"{frame['function']} ({frame['file']}:{frame['line']})"
            frames.append(f"  #{frame['index']}: {loc}".rstrip())
        stack_text = "\n".join(frames) if frames else "  No stack frames available."
        return textwrap.dedent(
            f"""\
            {header}
            Stack trace:
            {stack_text}
            """
        ).strip()

    def get_active_entry(self) -> HypothesisEntry | None:
        return self.hypotheses.get(self.active_id)

    def has_open_questions(self) -> bool:
        current = self.get_active_entry()
        return bool(current and current.open_questions)

    def _record_update(
        self,
        *,
        step_index: int | None,
        summary: str,
        payload: dict[str, Any],
        raw_payload: str | None,
        active_id: str,
    ) -> None:
        if step_index is not None:
            self.last_update_step = step_index
        entry = {
            "timestamp": time.time(),
            "step": step_index,
            "active_id": active_id,
            "summary": summary,
            "payload": payload,
            "raw": raw_payload,
            "phase_marker": payload.get("phase_marker") if isinstance(payload, dict) else None,
        }
        current = self.get_active_entry()
        if current:
            entry["open_questions"] = list(current.open_questions)
            entry["suggested_steps"] = list(current.suggested_steps)
            entry["evidence"] = list(current.evidence)
        self.update_log.append(entry)
        if len(self.update_log) > self.history_limit:
            self.update_log = self.update_log[-self.history_limit :]
