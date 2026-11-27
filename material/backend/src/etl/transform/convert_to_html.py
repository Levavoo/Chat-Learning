import re
from io import StringIO
from typing import ClassVar

from etl.models import DataType, PipelineItem
from etl.transform.base import Transform
from etl.transform.page_references import PageReferenceRewriter, heading_title, resolve_local_target
from etl.util.logging_setup import get_logger
from etl.util.parsing.dita import DitaDocument, DitaMetadata, DitaNode, DitaNodeType, DitaParser


class dita_to_html(Transform):
    """Transform that converts DITA XML to HTML."""

    output_type = DataType.HTML
    supported_input_types: ClassVar[list[DataType]] = [DataType.XML]
    transform_type = "DITA2HTML"

    logger = get_logger("DITA2HTML")

    _node_handlers: ClassVar[dict[DitaNodeType, str]] = {
        DitaNodeType.TOPIC: "_handle_topic",
        DitaNodeType.SECTION: "_handle_section",
        DitaNodeType.SECTION_DIV: "_handle_section_div",
        DitaNodeType.BODY_DIV: "_handle_section_div",
        DitaNodeType.PARAGRAPH: "_handle_paragraph",
        DitaNodeType.SUBHEADING: "_handle_subheading",
        DitaNodeType.ORDERED_LIST: "_handle_list",
        DitaNodeType.UNORDERED_LIST: "_handle_list",
        DitaNodeType.LIST_ITEM: "_handle_list_item",
        DitaNodeType.TABLE: "_handle_table",
        DitaNodeType.CODEBLOCK: "_handle_codeblock",
        DitaNodeType.NOTE: "_handle_note",
        DitaNodeType.BODY: "_handle_container",
    }

    _inline_tag_map: ClassVar[dict[DitaNodeType, str]] = {
        DitaNodeType.BOLD: "b",
        DitaNodeType.ITALIC: "i",
        DitaNodeType.EMPHASIS: "em",
        DitaNodeType.STRONG: "strong",
        DitaNodeType.UNDERLINE: "u",
        DitaNodeType.CODE: "code",
        DitaNodeType.SUBSCRIPT: "sub",
        DitaNodeType.SUPERSCRIPT: "sup",
        DitaNodeType.PHRASE: "span",
        DitaNodeType.TELETYPE: "code",
    }

    # Note type/othertype -> German label. DRV uses othertype="wichtig";
    # standard DITA type values stay for non-DRV content.
    _note_labels: ClassVar[dict[str, str]] = {
        "wichtig": "Bitte beachten Sie",
        "important": "Bitte beachten Sie",
        "tip": "Unser Tipp",
        "newsletter": "Newsletter",
        "note": "Hinweis",
    }

    def __init__(self) -> None:
        self._parser = DitaParser()

    def apply(self, item: PipelineItem) -> list[PipelineItem]:
        """Convert DITA XML to HTML."""
        self.logger.debug("Rendering DITA XML as HTML")

        if isinstance(item.data_object.data, bytes):
            data = item.data_object.data.decode("UTF-8")
        elif isinstance(item.data_object.data, str):
            data = item.data_object.data
        else:
            raise TypeError

        document = self._parser.parse_to_model(data)

        # Rewrite empty local page/chapter xrefs before rendering so the pass
        # sees prose cues and und/bis siblings on the primary doc and every
        # extracted note/table sub-document.
        if document.content is not None:
            PageReferenceRewriter(document.node_dict).rewrite(document.content)

        html = StringIO()
        html.write("<!DOCTYPE html>\n")
        html.write("<html>\n")
        self._render_document(document, html)
        html.write("</html>\n")

        data_object = item.data_object
        data_object.data = html.getvalue().strip()
        data_object.data_type = DataType.HTML

        return [item.model_copy(update={"data_object": data_object})]

    def _resolve_local_xref(self, href: str, node_dict: dict[str, DitaNode]) -> str | None:
        """Resolve a local href to its target heading title (SECTION/TITLE targets only)."""
        return heading_title(resolve_local_target(href, node_dict))

    def _render_document(self, document: DitaDocument, html: StringIO) -> None:
        self._render_metadata(document.metadata, html)

        if document.content:
            self._render_node(document.content, document.node_dict, html)

    def _render_node(self, node: DitaNode, node_dict: dict[str, DitaNode], html: StringIO) -> None:
        node_type = node.node_type

        if node_type in self._node_handlers:
            handler = getattr(self, self._node_handlers[node_type])
            handler(node, node_dict, html)
        elif node_type == DitaNodeType.TITLE:
            pass
        elif node_type in self._inline_tag_map:
            self._handle_inline_formatting(node, node_dict, html)
        elif node_type in (DitaNodeType.KEYWORD, DitaNodeType.WINTITLE):
            self._handle_span_class(node, node_dict, html)
        elif node_type == DitaNodeType.XREF:
            self._handle_xref(node, node_dict, html)
        elif node_type == DitaNodeType.FOOTNOTE:
            self._handle_footnote(node, node_dict, html)
        elif node_type == DitaNodeType.TEXT:
            html.write(node.text)
        else:
            self._handle_container(node, node_dict, html)

    def _handle_topic(self, node: DitaNode, node_dict: dict[str, DitaNode], html: StringIO) -> None:
        title_node = next((c for c in node.children if c.node_type == DitaNodeType.TITLE), None)

        html.write("<body>\n")
        html.write("<article>\n")
        if title_node:
            html.write(f"<h1>{title_node.text}</h1>\n")

        for child in node.children:
            if child.node_type != DitaNodeType.TITLE:
                self._render_node(child, node_dict, html)

        html.write("</article>\n</body>\n")

    def _handle_section(self, node: DitaNode, node_dict: dict[str, DitaNode], html: StringIO) -> None:
        title_node = next((c for c in node.children if c.node_type == DitaNodeType.TITLE), None)
        otherprops = node.attributes.get("otherprops")
        attrs = f" class='section-{otherprops}'" if otherprops else ""

        html.write(f"<section{attrs}>\n")
        if title_node:
            html.write(f"<h2>{title_node.text}</h2>\n")

        for child in node.children:
            if child.node_type != DitaNodeType.TITLE:
                self._render_node(child, node_dict, html)
        html.write("</section>\n")

    def _handle_section_div(self, node: DitaNode, node_dict: dict[str, DitaNode], html: StringIO) -> None:
        """Render <sectiondiv>/<bodydiv> as labelled <div>; title (if any) becomes <h3>."""
        title_node = next((c for c in node.children if c.node_type == DitaNodeType.TITLE), None)
        otherprops = node.attributes.get("otherprops")
        css_class = node.node_type.value.replace("_", "-")
        if otherprops:
            css_class = f"{css_class} {css_class}-{otherprops}"

        html.write(f"<div class='{css_class}'>\n")
        if title_node and title_node.text:
            html.write(f"<h3>{title_node.text}</h3>\n")
        for child in node.children:
            if child.node_type != DitaNodeType.TITLE:
                self._render_node(child, node_dict, html)
        html.write("</div>\n")

    def _handle_paragraph(self, node: DitaNode, node_dict: dict[str, DitaNode], html: StringIO) -> None:
        html.write("<p>")
        self._render_inline_content(node, node_dict, html)
        html.write("</p>\n")

    def _handle_subheading(self, node: DitaNode, node_dict: dict[str, DitaNode], html: StringIO) -> None:
        """Render a paragraph with otherprops=zwischenueberschrift as <h3>."""
        html.write("<h3>")
        self._render_inline_content(node, node_dict, html)
        html.write("</h3>\n")

    def _handle_list(self, node: DitaNode, node_dict: dict[str, DitaNode], html: StringIO) -> None:
        tag = "ol" if node.node_type == DitaNodeType.ORDERED_LIST else "ul"
        html.write(f"<{tag}>\n")
        for child in node.children:
            self._render_node(child, node_dict, html)
        html.write(f"</{tag}>\n")

    def _handle_list_item(self, node: DitaNode, node_dict: dict[str, DitaNode], html: StringIO) -> None:
        html.write("<li>")
        self._render_inline_content(node, node_dict, html)
        html.write("</li>\n")

    def _handle_table(self, node: DitaNode, node_dict: dict[str, DitaNode], html: StringIO) -> None:
        """Render a CALS table as a rectangular HTML table.

        Spans are expanded into a grid; a multi-row header is merged into one label
        per column. A full-width trailing row becomes a footnote paragraph; a
        full-width mid-table row stays in place as a section heading.
        """
        title_node = next((c for c in node.children if c.node_type == DitaNodeType.TITLE), None)
        if title_node and title_node.text:
            html.write(f"<h3>{title_node.text}</h3>\n")

        tgroup = next((c for c in node.children if c.node_type == DitaNodeType.TABLE_GROUP), node)
        header_rows, body_rows = self._split_header_body(tgroup)
        name_to_idx = self._column_index_map(tgroup)
        ncols = self._table_width(tgroup, header_rows, body_rows, name_to_idx)
        if ncols == 1:
            self._render_single_column_layout(header_rows + body_rows, node_dict, html)
            return

        if (
            not header_rows
            and body_rows
            and not self._is_full_width_row(self._table_entries(body_rows[0]), name_to_idx, ncols)
        ):
            # No explicit <thead>: promote only a normal first row, never a full-width band.
            header_rows, body_rows = body_rows[:1], body_rows[1:]

        header_grid, identity_cols = self._build_header_grid(header_rows, name_to_idx, ncols)
        labels = self._flatten_header(header_grid, identity_cols, ncols)
        body_grid, footnotes = self._build_body(body_rows, node_dict, name_to_idx, ncols)
        labels, body_grid = self._drop_empty_columns(labels, body_grid)

        html.write("<table>\n")
        if labels:
            html.write("<thead>\n<tr>\n")
            for label in labels:
                html.write(f"<th>{label}</th>\n")
            html.write("</tr>\n</thead>\n")
        if body_grid:
            html.write("<tbody>\n")
            for grid_row in body_grid:
                html.write("<tr>\n")
                for cell in grid_row:
                    html.write(f"<td>{cell}</td>\n")
                html.write("</tr>\n")
            html.write("</tbody>\n")
        html.write("</table>\n")

        for footnote in footnotes:
            # Only wrap bare inline content; a rendered block tag already stands on its own.
            html.write(footnote if footnote.startswith("<") else f"<p>{footnote}</p>")
            html.write("\n")

    def _render_single_column_layout(
        self, rows: list[DitaNode], node_dict: dict[str, DitaNode], html: StringIO
    ) -> None:
        """Linearize a one-column CALS layout table into normal document blocks.

        Bold-only paragraphs become headings; other cell content keeps its
        original paragraph/list structure. Arrow-only rows are skipped.
        """
        for row in rows:
            for entry in self._table_entries(row):
                text = self._get_node_text(entry).strip()
                if not text or text == "↓":
                    continue

                heading = self._single_column_heading(entry)
                if heading is not None:
                    html.write("<h3>")
                    self._render_inline_content(heading, node_dict, html)
                    html.write("</h3>\n")
                    continue

                rendered = self._render_entry_html(entry, node_dict)
                if not rendered or self._is_blank(rendered):
                    continue
                if re.match(r"^\s*<(?:p|ul|ol|h[1-6]|aside|div|pre|blockquote)\b", rendered):
                    html.write(rendered)
                else:
                    html.write(f"<p>{rendered}</p>")
                html.write("\n")

    def _single_column_heading(self, entry: DitaNode) -> DitaNode | None:
        """Return the bold node when an entry is exactly ``<p><b>…</b></p>``."""

        def significant(nodes: list[DitaNode]) -> list[DitaNode]:
            return [node for node in nodes if node.node_type != DitaNodeType.TEXT or node.text.strip()]

        entry_children = significant(entry.children)
        if len(entry_children) != 1 or entry_children[0].node_type != DitaNodeType.PARAGRAPH:
            return None

        paragraph = entry_children[0]
        paragraph_children = significant(paragraph.children)
        if (
            len(paragraph_children) == 1
            and paragraph_children[0].node_type in (DitaNodeType.BOLD, DitaNodeType.STRONG)
            and self._get_node_text(paragraph_children[0]).strip()
        ):
            return paragraph_children[0]
        return None

    def _split_header_body(self, tgroup: DitaNode) -> tuple[list[DitaNode], list[DitaNode]]:
        """Separate header rows (<thead>) from body rows (<tbody>/bare rows)."""
        header_rows: list[DitaNode] = []
        body_rows: list[DitaNode] = []
        for child in tgroup.children:
            if child.node_type == DitaNodeType.TABLE_ROW:
                body_rows.append(child)
            elif child.node_type == DitaNodeType.TABLE_GROUP:
                target = header_rows if child.attributes.get("table_section") == "thead" else body_rows
                target.extend(r for r in child.children if r.node_type == DitaNodeType.TABLE_ROW)
        return header_rows, body_rows

    def _column_index_map(self, tgroup: DitaNode) -> dict[str, int]:
        """Map CALS column names (from <colspec>) to zero-based grid indices."""
        colnames = [c for c in tgroup.attributes.get("colnames", "").split(",") if c]
        return {name: i for i, name in enumerate(colnames)}

    @staticmethod
    def _resolve_col(name: str | None, name_to_idx: dict[str, int]) -> int | None:
        """Resolve a colname to an index, falling back to a trailing 'colN' number."""
        if not name:
            return None
        if name in name_to_idx:
            return name_to_idx[name]
        match = re.search(r"(\d+)$", name)
        return int(match.group(1)) - 1 if match else None

    def _entry_span(self, entry: DitaNode, name_to_idx: dict[str, int], cursor: int) -> tuple[int, int]:
        """Return the (start, end) column range an entry occupies."""
        attrs = entry.attributes
        start = self._resolve_col(attrs.get("namest") or attrs.get("colname"), name_to_idx)
        if start is None:
            start = cursor
        end = self._resolve_col(attrs.get("nameend"), name_to_idx)
        if end is None or end < start:
            end = start
        return start, end

    def _table_width(
        self,
        tgroup: DitaNode,
        header_rows: list[DitaNode],
        body_rows: list[DitaNode],
        name_to_idx: dict[str, int],
    ) -> int:
        """Determine the column count: declared cols, colspecs, or widest row."""
        width = max(len(name_to_idx), int(tgroup.attributes.get("cols", "0") or 0))
        for row in header_rows + body_rows:
            cursor = 0
            for entry in (c for c in row.children if c.node_type == DitaNodeType.TABLE_ENTRY):
                _, end = self._entry_span(entry, name_to_idx, cursor)
                width = max(width, end + 1)
                cursor = end + 1
        return max(width, 1)

    def _table_entries(self, row: DitaNode) -> list[DitaNode]:
        """Return a row's <entry> cells in document order."""
        return [c for c in row.children if c.node_type == DitaNodeType.TABLE_ENTRY]

    @staticmethod
    def _occupy(occupied: list[bool], start: int, end: int, ncols: int) -> None:
        for col in range(max(start, 0), min(end + 1, ncols)):
            occupied[col] = True

    @staticmethod
    def _next_free(occupied: list[bool], cursor: int, ncols: int) -> int:
        while cursor < ncols and occupied[cursor]:
            cursor += 1
        return cursor

    def _consume_carryover(self, carryover: list[dict], cells: list[str], occupied: list[bool], ncols: int) -> None:
        """Apply active row spans to the current row, then drop exhausted ones."""
        for span in carryover:
            for col in range(max(span["start"], 0), min(span["end"] + 1, ncols)):
                occupied[col] = True
                cells[col] = span["text"]
            span["remaining"] -= 1
        carryover[:] = [s for s in carryover if s["remaining"] > 0]

    def _register_rowspan(self, carryover: list[dict], entry: DitaNode, start: int, end: int, text: str) -> None:
        morerows = int(entry.attributes.get("morerows", "0") or 0)
        if morerows > 0:
            carryover.append({"start": start, "end": end, "remaining": morerows, "text": text})

    def _build_header_grid(
        self, rows: list[DitaNode], name_to_idx: dict[str, int], ncols: int
    ) -> tuple[list[list[str]], set[int]]:
        """Expand header rows into a text grid, filling spanned positions.

        Also returns the set of "identity" columns (start columns of a header
        cell). A pure span-continuation column is left blank by ``_flatten_header``.
        """
        grid: list[list[str]] = []
        identity_cols: set[int] = set()
        carryover: list[dict] = []  # active rowspans: {start, end, remaining, text}
        for row in rows:
            cells = [""] * ncols
            occupied = [False] * ncols
            self._consume_carryover(carryover, cells, occupied, ncols)
            cursor = 0
            for entry in self._table_entries(row):
                cursor = self._next_free(occupied, cursor, ncols)
                start, end = self._entry_span(entry, name_to_idx, cursor)
                if 0 <= start < ncols:
                    identity_cols.add(start)
                text = self._get_node_text(entry).strip()
                for col in range(max(start, 0), min(end + 1, ncols)):
                    occupied[col] = True
                    cells[col] = text
                self._register_rowspan(carryover, entry, start, end, text)
                cursor = end + 1
            grid.append(cells)
        return grid, identity_cols

    def _flatten_header(self, header_grid: list[list[str]], identity_cols: set[int], ncols: int) -> list[str]:
        """Merge a multi-row header into one label per column (span-continuations stay blank)."""
        if not header_grid:
            return []
        labels: list[str] = []
        for col in range(ncols):
            if col not in identity_cols:
                labels.append("")
                continue
            parts: list[str] = []
            for grid_row in header_grid:
                text = grid_row[col] if col < len(grid_row) else ""
                if text and (not parts or parts[-1] != text):
                    parts.append(text)
            labels.append(" ".join(parts))
        return labels

    def _drop_empty_columns(self, labels: list[str], body_grid: list[list[str]]) -> tuple[list[str], list[list[str]]]:
        """Remove columns with no content anywhere (header + all body cells empty)."""
        if not labels:
            return labels, body_grid
        keep = [
            c for c in range(len(labels)) if labels[c].strip() or any(not self._is_blank(row[c]) for row in body_grid)
        ]
        if not keep or len(keep) == len(labels):
            return labels, body_grid
        new_labels = [labels[c] for c in keep]
        new_body = [[row[c] for c in keep] for row in body_grid]
        return new_labels, new_body

    def _is_full_width_row(self, entries: list[DitaNode], name_to_idx: dict[str, int], ncols: int) -> bool:
        """Return whether a row is a lone cell spanning every column (a band)."""
        if ncols < 2 or len(entries) != 1:
            return False
        start, end = self._entry_span(entries[0], name_to_idx, 0)
        return start <= 0 and end >= ncols - 1

    def _build_body(
        self,
        rows: list[DitaNode],
        node_dict: dict[str, DitaNode],
        name_to_idx: dict[str, int],
        ncols: int,
    ) -> tuple[list[list[str]], list[str]]:
        """Build the body grid; trailing full-width rows become footnotes, mid-table ones stay."""
        grid: list[list[str]] = []
        footnotes: list[str] = []
        carryover: list[dict] = []
        last_data = -1
        for i, row in enumerate(rows):
            if not self._is_full_width_row(self._table_entries(row), name_to_idx, ncols):
                last_data = i
        for i, row in enumerate(rows):
            entries = self._table_entries(row)
            cells = [""] * ncols
            occupied = [False] * ncols
            # Consume active rowspans first so every row counts toward the span's coverage.
            self._consume_carryover(carryover, cells, occupied, ncols)
            if self._is_full_width_row(entries, name_to_idx, ncols):
                rendered = self._render_entry_html(entries[0], node_dict)
                if last_data >= 0 and i > last_data:
                    footnotes.append(rendered)
                else:
                    grid.append([rendered] + [""] * (ncols - 1))
                continue

            cursor = 0
            for entry in entries:
                cursor = self._next_free(occupied, cursor, ncols)
                start, end = self._entry_span(entry, name_to_idx, cursor)
                if 0 <= start < ncols:
                    cells[start] = self._render_entry_html(entry, node_dict)
                self._occupy(occupied, start, end, ncols)
                self._register_rowspan(carryover, entry, start, end, "")
                cursor = end + 1
            if any(not self._is_blank(c) for c in cells):
                grid.append(cells)
        return grid, footnotes

    @staticmethod
    def _is_blank(cell: str) -> bool:
        """Whether a rendered cell has no visible text (only tags/whitespace)."""
        return not re.sub(r"<[^>]*>", "", cell).strip()

    def _render_entry_html(self, entry: DitaNode, node_dict: dict[str, DitaNode]) -> str:
        """Render an entry's inline content to an HTML string (preserving formatting)."""
        buffer = StringIO()
        self._render_inline_content(entry, node_dict, buffer)
        return buffer.getvalue().strip()

    def _handle_codeblock(self, node: DitaNode, node_dict: dict[str, DitaNode], html: StringIO) -> None:
        html.write(f"<pre><code>{node.text}</code></pre>\n")

    def _handle_note(self, node: DitaNode, node_dict: dict[str, DitaNode], html: StringIO) -> None:
        note_type = node.attributes.get("type", "note")
        # Prefer the author's explicit <p otherprops="note-ueberschrift"> heading over a type-based label.
        author_heading = next(
            (
                c
                for c in node.children
                if c.node_type == DitaNodeType.PARAGRAPH
                and c.attributes.get("otherprops") == "note-ueberschrift"
                and c.text
            ),
            None,
        )
        if author_heading:
            label = author_heading.text.strip().rstrip(":").strip()
        else:
            other_type = node.attributes.get("othertype", "")
            label_key = other_type if other_type else note_type
            # ``unbekannt`` is structural metadata, not a real heading — never render it.
            label = None if label_key == "unbekannt" else self._note_labels.get(label_key, label_key.title())

        html.write(f"<aside class='note note-{note_type}'>\n")
        if label:
            html.write(f"<strong>{label}:</strong>\n")
        for child in node.children:
            if child is author_heading:
                continue
            self._render_node(child, node_dict, html)
        html.write("</aside>\n")

    def _handle_container(self, node: DitaNode, node_dict: dict[str, DitaNode], html: StringIO) -> None:
        for child in node.children:
            self._render_node(child, node_dict, html)

    def _render_inline_content(self, node: DitaNode, node_dict: dict[str, DitaNode], html: StringIO) -> None:
        if node.text and not node.children:
            html.write(node.text)
            return

        for child in node.children:
            self._render_inline_node(child, node_dict, html)

    def _render_inline_node(self, node: DitaNode, node_dict: dict[str, DitaNode], html: StringIO) -> None:
        node_type = node.node_type

        if node_type == DitaNodeType.TEXT:
            html.write(node.text)

        elif node_type in self._inline_tag_map:
            tag = self._inline_tag_map[node_type]
            html.write(f"<{tag}>")
            self._render_inline_content(node, node_dict, html)
            html.write(f"</{tag}>")

        elif node_type == DitaNodeType.WINTITLE:
            html.write("<h3>")
            self._render_inline_content(node, node_dict, html)
            html.write("</h3>")

        elif node_type == DitaNodeType.KEYWORD:
            html.write(f"<span class='{node_type.value}'>")
            self._render_inline_content(node, node_dict, html)
            html.write("</span>")

        elif node_type == DitaNodeType.XREF:
            self._handle_xref(node, node_dict, html)

        elif node_type == DitaNodeType.FOOTNOTE:
            self._handle_footnote(node, node_dict, html)

        elif node_type in self._node_handlers:
            self._render_node(node, node_dict, html)

        else:
            self._render_inline_content(node, node_dict, html)

    def _handle_inline_formatting(self, node: DitaNode, node_dict: dict[str, DitaNode], html: StringIO) -> None:
        tag = self._inline_tag_map.get(node.node_type, "span")
        html.write(f"<{tag}>")
        self._render_inline_content(node, node_dict, html)
        html.write(f"</{tag}>")

    def _handle_span_class(self, node: DitaNode, node_dict: dict[str, DitaNode], html: StringIO) -> None:
        if node.node_type == DitaNodeType.WINTITLE:
            html.write("<h3>")
            self._render_inline_content(node, node_dict, html)
            html.write("</h3>")
        else:
            html.write(f"<span class='{node.node_type.value}'>")
            self._render_inline_content(node, node_dict, html)
            html.write("</span>")

    def _handle_xref(self, node: DitaNode, node_dict: dict[str, DitaNode], html: StringIO) -> None:
        href = node.attributes.get("href", "#")
        scope = node.attributes.get("scope", "local")
        link_text = self._get_node_text(node)

        if scope == "local":
            resolved_text = self._resolve_local_xref(href, node_dict)
            if resolved_text:
                link_text = resolved_text
            if link_text:
                html.write(f'"{link_text}"')
        else:
            if link_text:
                html.write(f"<a href='{href}'>{link_text}</a>")
            else:
                html.write(f"<a href='{href}'>{href}</a>")

    def _handle_footnote(self, node: DitaNode, node_dict: dict[str, DitaNode], html: StringIO) -> None:
        html.write("(")
        self._render_footnote_content(node, node_dict, html)
        html.write(")")

    def _render_footnote_content(self, node: DitaNode, node_dict: dict[str, DitaNode], html: StringIO) -> None:
        if node.text and not node.children:
            html.write(node.text)
            return

        for child in node.children:
            if child.node_type == DitaNodeType.PARAGRAPH:
                self._render_footnote_content(child, node_dict, html)
            elif child.node_type == DitaNodeType.TEXT:
                html.write(child.text)
            elif child.node_type == DitaNodeType.XREF:
                self._handle_xref(child, node_dict, html)
            else:
                self._render_inline_node(child, node_dict, html)

    def _get_node_text(self, node: DitaNode) -> str:
        if node.text:
            return node.text

        parts = []
        for child in node.children:
            parts.append(self._get_node_text(child))
        return "".join(parts)

    def _render_metadata(self, metadata: DitaMetadata, html: StringIO) -> None:
        html.write("<head>\n")

        for name, value in metadata.custom_data.items():
            html.write(f'<meta name="{name}" content="{value}">\n')

        if metadata.category:
            html.write(f'<meta name="category" content="{metadata.category}">\n')

        if metadata.keywords:
            html.write(f'<meta name="tags" content="{", ".join(metadata.keywords)}">\n')

        html.write("</head>\n")
