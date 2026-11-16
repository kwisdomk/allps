"""ExportService — sovereign learner handover document export pipeline.

Strictly enforces the ALLPS Dual-View Approval Boundary:
- Only human-accepted patterns returned by ReviewService.get_surfaced_profile()
  (with verified SHA-256 content hashes) may appear in exported documents.
- Pending, rejected, and needs-context candidate patterns are never exported.
- Cited supporting and conflicting evidence provenance is resolved from SQLiteStore.
- Every export action is recorded in the audit log.
"""

from __future__ import annotations

from datetime import datetime, timezone
import html
import json
import textwrap
from typing import Any

from allps.models.audit import AuditEntry
from allps.models.evidence import Evidence
from allps.services.review_service import ReviewService
from allps.storage.sqlite_store import SQLiteStore

SUPPORTED_EXPORT_FORMATS = ("pdf", "html", "md", "json")


def _sanitize_pdf_text(text: str) -> str:
    """Normalize text to printable WinAnsi / Latin-1 range and escape PDF string literals."""
    replacements = {
        "\u2014": "--",
        "\u2013": "-",
        "\u2018": "'",
        "\u2019": "'",
        "\u201c": '"',
        "\u201d": '"',
        "\u2022": "*",
        "\u2026": "...",
        "\u00a0": " ",
        "\u2713": "[OK]",
        "\u2715": "[X]",
        "\u2192": "->",
    }
    out = text
    for src, dst in replacements.items():
        out = out.replace(src, dst)
    # Fall back safely for any characters outside Latin-1
    encoded = out.encode("latin-1", errors="replace").decode("latin-1")
    return (
        encoded.replace("\\", "\\\\")
        .replace("(", "\\(")
        .replace(")", "\\)")
    )


def _format_evidence_outcome(ev: Evidence) -> str:
    """Produce a concise, faithful outcome summary for a cited Evidence record."""
    c = ev.content if isinstance(ev.content, dict) else dict(ev.content)
    if ev.is_missing_outcome:
        status = c.get("status", "missing")
        reason = c.get("reason", "no reason recorded")
        return f"Missing ({status}): {reason}"
    if ev.is_marks:
        return f"Score {c.get('score')}/{c.get('max_score')}"
    if ev.is_rubric:
        level = c.get("level") or c.get("ordinal_level") or c.get("rubric_level")
        rubric = c.get("rubric") or c.get("rubric_name") or "Rubric"
        return f"{rubric}: {level}"
    if ev.is_fluency:
        return f"{c.get('value')} {c.get('unit')}"
    if ev.evidence_type.value == "attendance":
        if "days_present" in c and "days_total" in c:
            return f"Attendance {c['days_present']}/{c['days_total']} days"
        return f"Attendance: {c.get('status', 'recorded')}"
    text = c.get("observation") or c.get("note") or c.get("reflection") or c.get("summary")
    if text:
        clean = " ".join(str(text).split())
        return clean if len(clean) <= 140 else clean[:137] + "..."
    return json.dumps(c, ensure_ascii=False)


def _serialize_cited_evidence(ev: Evidence) -> dict[str, Any]:
    """Serialize cited evidence provenance for handover documents."""
    return {
        "evidence_id": ev.evidence_id,
        "evidence_type": ev.evidence_type.value,
        "academic_year": ev.academic_year,
        "term": ev.term,
        "subject": ev.subject,
        "assessment_stage": ev.assessment_stage,
        "grade": ev.grade,
        "observed_at": ev.observed_at.isoformat(),
        "source_system": ev.source_system,
        "ingestion_method": ev.ingestion_method.value,
        "source_type": ev.source_type,
        "source_reference": ev.source_reference,
        "source_event_id": ev.source_event_id,
        "outcome_summary": _format_evidence_outcome(ev),
    }


class _SimplePDFBuilder:
    """Minimal zero-dependency PDF 1.4 writer with Helvetica, Helvetica-Bold, and Courier."""

    PAGE_WIDTH = 595.28
    PAGE_HEIGHT = 841.89
    MARGIN_X = 48.0
    TOP_Y = 792.0
    BOTTOM_Y = 54.0

    def __init__(self) -> None:
        self._pages: list[list[str]] = [[]]
        self._y = self.TOP_Y

    def _new_page(self) -> None:
        self._pages.append([])
        self._y = self.TOP_Y

    def _ensure_space(self, needed: float) -> None:
        if self._y - needed < self.BOTTOM_Y:
            self._new_page()

    def add_spacer(self, points: float = 8.0) -> None:
        self._y -= points
        if self._y < self.BOTTOM_Y:
            self._new_page()

    def add_rule(self) -> None:
        self._ensure_space(12.0)
        y = self._y
        x1 = self.MARGIN_X
        x2 = self.PAGE_WIDTH - self.MARGIN_X
        self._pages[-1].append(
            f"0.82 0.84 0.87 RG 0.6 w {x1:.2f} {y:.2f} m {x2:.2f} {y:.2f} l S 0 0 0 RG"
        )
        self._y -= 10.0

    def add_wrapped(
        self,
        text: str,
        *,
        font: str = "F1",
        size: float = 10.0,
        leading: float = 14.0,
        indent: float = 0.0,
        max_chars: int = 88,
        rgb: tuple[float, float, float] = (0.11, 0.11, 0.12),
    ) -> None:
        lines: list[str] = []
        for paragraph in str(text).splitlines() or [""]:
            wrapped = textwrap.wrap(paragraph, width=max_chars) or [""]
            lines.extend(wrapped)
        r, g, b = rgb
        x = self.MARGIN_X + indent
        for line in lines:
            self._ensure_space(leading)
            safe = _sanitize_pdf_text(line)
            self._pages[-1].append(
                f"BT /{font} {size:.1f} Tf {r:.2f} {g:.2f} {b:.2f} rg "
                f"{x:.2f} {self._y:.2f} Td ({safe}) Tj ET"
            )
            self._y -= leading

    def build(self) -> bytes:
        """Assemble complete PDF bytes with page footers and accurate xref offsets."""
        total_pages = len(self._pages)
        for idx, ops in enumerate(self._pages, start=1):
            footer = _sanitize_pdf_text(
                f"ALLPS Approved Learner Transition Handover  |  Page {idx} of {total_pages}"
            )
            ops.append(
                f"BT /F1 8.5 Tf 0.45 0.45 0.48 rg {self.MARGIN_X:.2f} 28.00 Td ({footer}) Tj ET"
            )

        # Object numbering:
        # 1: Catalog, 2: Pages, 3: Helvetica, 4: Helvetica-Bold, 5: Courier
        # Then for each page i (0..N-1): page_obj = 6 + 2*i, content_obj = 7 + 2*i
        objects: list[bytes] = []
        page_refs = " ".join(f"{6 + 2 * i} 0 R" for i in range(total_pages))

        objects.append(b"<< /Type /Catalog /Pages 2 0 R >>")
        objects.append(f"<< /Type /Pages /Kids [{page_refs}] /Count {total_pages} >>".encode("ascii"))
        objects.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>")
        objects.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold /Encoding /WinAnsiEncoding >>")
        objects.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Courier /Encoding /WinAnsiEncoding >>")

        for i, ops in enumerate(self._pages):
            page_num = 6 + 2 * i
            content_num = page_num + 1
            stream_bytes = "\n".join(ops).encode("latin-1", errors="replace")
            page_dict = (
                f"<< /Type /Page /Parent 2 0 R "
                f"/MediaBox [0 0 {self.PAGE_WIDTH:.2f} {self.PAGE_HEIGHT:.2f}] "
                f"/Resources << /Font << /F1 3 0 R /F2 4 0 R /F3 5 0 R >> >> "
                f"/Contents {content_num} 0 R >>"
            ).encode("ascii")
            content_obj = (
                f"<< /Length {len(stream_bytes)} >>\nstream\n".encode("ascii")
                + stream_bytes
                + b"\nendstream"
            )
            objects.append(page_dict)
            objects.append(content_obj)

        buf = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
        offsets: list[int] = [0]
        for obj_id, body in enumerate(objects, start=1):
            offsets.append(len(buf))
            buf.extend(f"{obj_id} 0 obj\n".encode("ascii"))
            buf.extend(body)
            buf.extend(b"\nendobj\n")

        xref_pos = len(buf)
        buf.extend(f"xref\n0 {len(objects) + 1}\n".encode("ascii"))
        buf.extend(b"0000000000 65535 f \n")
        for off in offsets[1:]:
            buf.extend(f"{off:010d} 00000 n \n".encode("ascii"))

        buf.extend(
            (
                f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
                f"startxref\n{xref_pos}\n%%EOF\n"
            ).encode("ascii")
        )
        return bytes(buf)


class ExportService:
    """Renders sovereign human-approved learner handover documents."""

    def __init__(self, store: SQLiteStore, review_service: ReviewService) -> None:
        self._store = store
        self._review_service = review_service

    async def build_handover_document_data(self, learner_id: str) -> dict[str, Any]:
        """Assemble strictly approved handover data with SHA-256 verification and cited evidence."""
        learner = await self._store.get_learner(learner_id)
        if not learner:
            raise ValueError(f"Learner '{learner_id}' not found.")

        # Dual-view gate: strictly human-accepted patterns with verified SHA-256 hashes
        profile = await self._review_service.get_surfaced_profile(learner_id)
        patterns = profile.get("patterns", [])

        cited_ids: list[str] = []
        for pat in patterns:
            cited_ids.extend(pat.get("supporting_evidence", []))
            cited_ids.extend(pat.get("conflicting_evidence", []))

        evidence_map = await self._store.get_evidence_by_ids(cited_ids)
        cited_evidence = {
            eid: _serialize_cited_evidence(ev)
            for eid, ev in evidence_map.items()
        }

        exported_at = datetime.now(timezone.utc).isoformat()
        doc_data = {
            "document_type": "allps_approved_transition_handover",
            "governance_policy": "sovereign_human_approved_only",
            "exported_at": exported_at,
            "learner": {
                "learner_id": learner.learner_id,
                "display_name": learner.display_name,
                "created_at": learner.created_at.isoformat(),
            },
            "accepted_pattern_count": len(patterns),
            "patterns": patterns,
            "cited_evidence": cited_evidence,
        }

        audit = AuditEntry(
            tool_name="export_handover_document",
            input_summary={
                "learner_id": learner_id,
                "accepted_pattern_count": len(patterns),
                "cited_evidence_count": len(cited_evidence),
            },
            output_reference=learner_id,
            approval_state=f"exported_{len(patterns)}_approved_patterns",
        )
        await self._store.add_audit_entry(audit)

        return doc_data

    async def export_handover(
        self,
        learner_id: str,
        fmt: str = "pdf",
    ) -> tuple[bytes, str, str]:
        """Render an approved learner handover document in the requested format.

        Returns (content_bytes, media_type, file_extension).
        """
        clean_fmt = (fmt or "pdf").strip().lower()
        if clean_fmt not in SUPPORTED_EXPORT_FORMATS:
            raise ValueError(
                f"Unsupported export format '{fmt}'. Must be one of: {', '.join(SUPPORTED_EXPORT_FORMATS)}."
            )

        data = await self.build_handover_document_data(learner_id)

        if clean_fmt == "json":
            content = json.dumps(data, indent=2, ensure_ascii=False).encode("utf-8")
            return content, "application/json", "json"
        if clean_fmt == "md":
            content = self._render_markdown(data).encode("utf-8")
            return content, "text/markdown; charset=utf-8", "md"
        if clean_fmt == "html":
            content = self._render_html(data).encode("utf-8")
            return content, "text/html; charset=utf-8", "html"
        return self._render_pdf(data), "application/pdf", "pdf"

    @staticmethod
    def _render_markdown(data: dict[str, Any]) -> str:
        learner = data["learner"]
        patterns = data["patterns"]
        cited = data["cited_evidence"]

        lines = [
            "# ALLPS — Approved Learner Transition Handover",
            "",
            f"- **Learner:** {learner['display_name']} (`{learner['learner_id']}`)",
            f"- **Exported At (UTC):** {data['exported_at']}",
            f"- **Approved Findings:** {data['accepted_pattern_count']}",
            "- **Governance Boundary:** Strictly human-approved findings with verified SHA-256 content hashes. Pending, rejected, and unverified drafts are excluded.",
            "",
        ]

        if not patterns:
            lines.append("_No human-approved transition findings are currently published for this learner._")
            return "\n".join(lines) + "\n"

        for idx, pat in enumerate(patterns, start=1):
            rev = pat.get("review", {})
            lines.extend([
                f"## Finding {idx}: {pat['pattern_type'].upper()}",
                "",
                pat["summary"],
                "",
                f"- **Pattern ID:** `{pat['pattern_id']}`",
                f"- **Approved By:** `{rev.get('reviewer_id')}`",
                f"- **Resolved At (UTC):** {rev.get('resolved_at')}",
                f"- **Decision Revision:** {rev.get('revision', 0)}",
                f"- **SHA-256 Snapshot:** `{rev.get('approved_content_hash')}` (verified={rev.get('hash_verified')})",
            ])
            if rev.get("teacher_notes"):
                lines.append(f"- **Teacher Notes:** {rev['teacher_notes']}")
            if pat.get("limitations"):
                lines.append(f"- **Limitations:** {'; '.join(pat['limitations'])}")

            all_refs = list(
                dict.fromkeys(pat.get("supporting_evidence", []) + pat.get("conflicting_evidence", []))
            )
            if all_refs:
                lines.extend(["", "### Cited Evidence"])
                for eid in all_refs:
                    ev = cited.get(eid)
                    if ev:
                        subj = ev.get("subject") or "General"
                        stage = f" [{ev['assessment_stage']}]" if ev.get("assessment_stage") else ""
                        lines.append(
                            f"- `{eid}` — Year {ev['academic_year']} Term {ev['term']} | {subj} | "
                            f"{ev['evidence_type']}{stage} | {ev['outcome_summary']} "
                            f"(Source: {ev['source_reference']} via {ev['source_system']})"
                        )
                    else:
                        lines.append(f"- `{eid}`")
            lines.append("")

        return "\n".join(lines)

    @staticmethod
    def _render_html(data: dict[str, Any]) -> str:
        learner = data["learner"]
        patterns = data["patterns"]
        cited = data["cited_evidence"]

        findings_blocks: list[str] = []
        if not patterns:
            findings_blocks.append(
                '<div class="empty">No human-approved transition findings are currently published for this learner.</div>'
            )
        else:
            for idx, pat in enumerate(patterns, start=1):
                rev = pat.get("review", {})
                all_refs = list(
                    dict.fromkeys(pat.get("supporting_evidence", []) + pat.get("conflicting_evidence", []))
                )
                cite_rows = []
                for eid in all_refs:
                    ev = cited.get(eid)
                    if ev:
                        subj = html.escape(ev.get("subject") or "General")
                        stage = html.escape(ev.get("assessment_stage") or "-")
                        cite_rows.append(
                            "<tr>"
                            f"<td><code>{html.escape(eid[:8])}…</code></td>"
                            f"<td>Y{ev['academic_year']} T{ev['term']}</td>"
                            f"<td>{subj}</td>"
                            f"<td>{html.escape(ev['evidence_type'])} ({stage})</td>"
                            f"<td>{html.escape(ev['outcome_summary'])}</td>"
                            f"<td>{html.escape(ev['source_reference'])} (<code>{html.escape(ev['source_system'])}</code>)</td>"
                            "</tr>"
                        )
                    else:
                        cite_rows.append(
                            f"<tr><td><code>{html.escape(eid)}</code></td><td colspan='5'>Evidence record reference</td></tr>"
                        )

                notes_html = (
                    f"<p><strong>Teacher Notes:</strong> {html.escape(rev['teacher_notes'])}</p>"
                    if rev.get("teacher_notes")
                    else ""
                )
                limits_html = (
                    f"<p><strong>Limitations:</strong> {html.escape('; '.join(pat['limitations']))}</p>"
                    if pat.get("limitations")
                    else ""
                )
                cites_table = (
                    "<table class='cite-table'><thead><tr>"
                    "<th>Evidence ID</th><th>Period</th><th>Subject</th><th>Type / Stage</th><th>Outcome</th><th>Attribution</th>"
                    "</tr></thead><tbody>"
                    + "".join(cite_rows)
                    + "</tbody></table>"
                    if cite_rows
                    else ""
                )

                findings_blocks.append(
                    f"""
                    <section class="finding-card">
                      <div class="finding-head">
                        <span class="pill">{idx}. {html.escape(pat['pattern_type'].upper())}</span>
                        <span class="pill approved">APPROVED PROFILE</span>
                      </div>
                      <p class="finding-summary">{html.escape(pat['summary'])}</p>
                      <div class="meta-grid">
                        <div><strong>Approved By:</strong> <code>{html.escape(str(rev.get('reviewer_id') or ''))}</code></div>
                        <div><strong>Resolved (UTC):</strong> {html.escape(str(rev.get('resolved_at') or ''))}</div>
                        <div><strong>SHA-256 Snapshot:</strong> <code>{html.escape(str(rev.get('approved_content_hash') or ''))}</code></div>
                        <div><strong>Pattern ID:</strong> <code>{html.escape(pat['pattern_id'])}</code></div>
                      </div>
                      {notes_html}
                      {limits_html}
                      {cites_table}
                    </section>
                    """
                )

        return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <title>ALLPS Approved Handover — {html.escape(learner['learner_id'])}</title>
  <style>
    @page {{ margin: 16mm; }}
    body {{
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Arial, sans-serif;
      color: #1d1d1f;
      background: #f5f5f7;
      margin: 0;
      padding: 24px;
      line-height: 1.5;
    }}
    .sheet {{
      max-width: 900px;
      margin: 0 auto;
      background: #ffffff;
      border: 1px solid #d2d2d7;
      border-radius: 10px;
      padding: 28px 32px;
    }}
    .toolbar {{
      display: flex;
      justify-content: flex-end;
      gap: 10px;
      margin-bottom: 16px;
    }}
    .btn-print {{
      background: #0071e3;
      color: #fff;
      border: none;
      border-radius: 6px;
      padding: 8px 14px;
      font-size: 13px;
      font-weight: 600;
      cursor: pointer;
    }}
    header.doc-header {{
      border-bottom: 2px solid #1d1d1f;
      padding-bottom: 14px;
      margin-bottom: 18px;
    }}
    h1 {{ font-size: 20px; margin: 0 0 6px 0; }}
    .sub {{ font-size: 12.5px; color: #515154; margin: 0; }}
    .learner-bar {{
      display: grid;
      grid-template-columns: repeat(3, 1fr);
      gap: 10px;
      background: #f5f5f7;
      padding: 12px 14px;
      border-radius: 8px;
      margin-bottom: 18px;
      font-size: 13px;
    }}
    .finding-card {{
      border: 1px solid #d2d2d7;
      border-radius: 8px;
      padding: 16px 18px;
      margin-bottom: 16px;
      break-inside: avoid;
    }}
    .finding-head {{
      display: flex;
      justify-content: space-between;
      align-items: center;
      margin-bottom: 10px;
    }}
    .pill {{
      font-size: 11px;
      font-weight: 700;
      text-transform: uppercase;
      letter-spacing: 0.04em;
      padding: 3px 8px;
      border-radius: 4px;
      background: #f2f2f7;
      color: #3a3a3c;
    }}
    .pill.approved {{
      background: #e6f4ea;
      color: #137333;
    }}
    .finding-summary {{ font-size: 14.5px; font-weight: 500; margin: 0 0 12px 0; }}
    .meta-grid {{
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 6px 14px;
      font-size: 12px;
      color: #424245;
      background: #fbfbfd;
      padding: 10px;
      border-radius: 6px;
      margin-bottom: 10px;
    }}
    .cite-table {{
      width: 100%;
      border-collapse: collapse;
      margin-top: 10px;
      font-size: 11.5px;
    }}
    .cite-table th, .cite-table td {{
      border: 1px solid #e5e5ea;
      padding: 6px 8px;
      text-align: left;
      vertical-align: top;
    }}
    .cite-table th {{ background: #f5f5f7; font-weight: 600; }}
    code {{ font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; font-size: 11px; }}
    .empty {{ padding: 24px; text-align: center; color: #6e6e73; border: 1px dashed #d2d2d7; border-radius: 8px; }}
    @media print {{
      body {{ background: #ffffff; padding: 0; }}
      .sheet {{ border: none; padding: 0; max-width: none; }}
      .no-print {{ display: none !important; }}
    }}
  </style>
</head>
<body>
  <div class="sheet">
    <div class="toolbar no-print">
      <button type="button" class="btn-print" onclick="window.print()">Print / Save as PDF</button>
    </div>
    <header class="doc-header">
      <h1>ALLPS — Approved Learner Transition Handover</h1>
      <p class="sub">Sovereign Human-Approved Profile Only (Unreviewed, Pending, and Rejected Drafts Excluded)</p>
    </header>
    <div class="learner-bar">
      <div><strong>Learner:</strong> {html.escape(learner['display_name'])}</div>
      <div><strong>Learner ID:</strong> <code>{html.escape(learner['learner_id'])}</code></div>
      <div><strong>Exported (UTC):</strong> {html.escape(data['exported_at'])}</div>
    </div>
    {''.join(findings_blocks)}
  </div>
</body>
</html>
"""

    @staticmethod
    def _render_pdf(data: dict[str, Any]) -> bytes:
        learner = data["learner"]
        patterns = data["patterns"]
        cited = data["cited_evidence"]

        pdf = _SimplePDFBuilder()
        pdf.add_wrapped(
            "ALLPS -- Approved Learner Transition Handover",
            font="F2",
            size=16.0,
            leading=20.0,
            max_chars=62,
        )
        pdf.add_wrapped(
            "Sovereign Human-Approved Profile Only (Pending & Rejected Drafts Excluded)",
            font="F1",
            size=9.5,
            leading=13.0,
            max_chars=90,
            rgb=(0.35, 0.35, 0.38),
        )
        pdf.add_spacer(4.0)
        pdf.add_rule()

        pdf.add_wrapped(
            f"Learner: {learner['display_name']} ({learner['learner_id']})",
            font="F2",
            size=11.0,
            leading=15.0,
            max_chars=82,
        )
        pdf.add_wrapped(
            f"Exported At (UTC): {data['exported_at']}   |   Approved Findings: {data['accepted_pattern_count']}",
            font="F1",
            size=9.5,
            leading=14.0,
            max_chars=90,
            rgb=(0.30, 0.30, 0.34),
        )
        pdf.add_spacer(8.0)

        if not patterns:
            pdf.add_rule()
            pdf.add_wrapped(
                "No human-approved transition findings are currently published for this learner.",
                font="F1",
                size=10.5,
                leading=15.0,
                max_chars=85,
            )
            return pdf.build()

        for idx, pat in enumerate(patterns, start=1):
            rev = pat.get("review", {})
            pdf.add_rule()
            pdf.add_wrapped(
                f"Finding {idx}: {pat['pattern_type'].upper()}  [APPROVED]",
                font="F2",
                size=11.5,
                leading=16.0,
                max_chars=78,
                rgb=(0.08, 0.38, 0.18),
            )
            pdf.add_spacer(2.0)
            pdf.add_wrapped(
                pat["summary"],
                font="F1",
                size=10.5,
                leading=14.5,
                max_chars=86,
            )
            pdf.add_spacer(4.0)
            pdf.add_wrapped(
                f"Approved By: {rev.get('reviewer_id')}   |   Resolved (UTC): {rev.get('resolved_at')}   |   Rev: {rev.get('revision', 0)}",
                font="F1",
                size=9.0,
                leading=13.0,
                max_chars=94,
                rgb=(0.28, 0.28, 0.31),
            )
            pdf.add_wrapped(
                f"SHA-256 Snapshot: {rev.get('approved_content_hash')}",
                font="F3",
                size=8.5,
                leading=12.0,
                max_chars=92,
                rgb=(0.22, 0.22, 0.25),
            )
            if rev.get("teacher_notes"):
                pdf.add_wrapped(
                    f"Teacher Notes: {rev['teacher_notes']}",
                    font="F1",
                    size=9.5,
                    leading=13.5,
                    max_chars=88,
                )
            if pat.get("limitations"):
                pdf.add_wrapped(
                    f"Limitations: {'; '.join(pat['limitations'])}",
                    font="F1",
                    size=9.0,
                    leading=13.0,
                    max_chars=90,
                    rgb=(0.45, 0.28, 0.05),
                )

            all_refs = list(
                dict.fromkeys(pat.get("supporting_evidence", []) + pat.get("conflicting_evidence", []))
            )
            if all_refs:
                pdf.add_spacer(4.0)
                pdf.add_wrapped(
                    "Cited Evidence Provenance:",
                    font="F2",
                    size=9.5,
                    leading=13.0,
                    max_chars=88,
                )
                for eid in all_refs:
                    ev = cited.get(eid)
                    if ev:
                        subj = ev.get("subject") or "General"
                        stage = f" [{ev['assessment_stage']}]" if ev.get("assessment_stage") else ""
                        line = (
                            f"- {eid[:8]}... | Y{ev['academic_year']} T{ev['term']} | {subj} | "
                            f"{ev['evidence_type']}{stage} | {ev['outcome_summary']} "
                            f"(Source: {ev['source_reference']} via {ev['source_system']})"
                        )
                    else:
                        line = f"- {eid}"
                    pdf.add_wrapped(
                        line,
                        font="F1",
                        size=8.5,
                        leading=12.0,
                        indent=8.0,
                        max_chars=92,
                        rgb=(0.20, 0.20, 0.24),
                    )
            pdf.add_spacer(6.0)

        return pdf.build()

