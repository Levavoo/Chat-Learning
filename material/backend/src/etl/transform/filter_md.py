import re
from typing import ClassVar

from etl.models import DataType, PipelineItem
from etl.transform.base import Transform
from etl.util.logging_setup import get_logger


class filter_markdown_sections(Transform):
    r"""Transform that uses a white and/or blacklist to to filter markdown sections by looking at section headers.

    input_types:
        DataType.MARKDOWN
    output_type:
        DataType.MARKDOWN
    name:
        \"MD_FILTER\"
    """

    output_type = DataType.MARKDOWN
    supported_input_types: ClassVar[list[DataType]] = [DataType.MARKDOWN]
    transform_type = "MD_FILTER"

    logger = get_logger("MD_FILTER")

    def __init__(
        self,
        blacklist: list[str] | None,
        whitelist: list[str] | None,
        case_sensetive: bool = False,
    ) -> None:
        self._blacklist = self._compile_regex_patterns(blacklist)
        self._whitelist = self._compile_regex_patterns(whitelist)
        self._case_sensitive = case_sensetive

    def _compile_regex_patterns(self, patterns: list[str] | None) -> list[re.Pattern]:
        out_patterns: list[re.Pattern] = []

        if not patterns:
            return []
        for p in patterns:
            compiled = re.escape(p).replace(r" \*", ".*")
            out_patterns.append(re.compile(f"^{compiled}$", re.IGNORECASE))
        return out_patterns

    def apply(self, item: PipelineItem) -> list[PipelineItem]:
        self.logger.debug(
            f"Applying header filter. Whitelist: {len(self._whitelist)} | Blacklist: {len(self._blacklist)}"
        )

        if not (self._blacklist or self._whitelist):
            return [item]
        if not isinstance(item.data_object.data, str):
            raise TypeError(f"Expected str, got {type(item.data_object.data).__name__}")
        md_lines = item.data_object.data.splitlines()

        filtered_lines: list = []
        header_stack: list = []

        header_re = re.compile(r"^(#{1,6})\s*(.+)$")

        keep_section = True
        for line in md_lines:
            match = header_re.match(line)
            if match:
                level, header_text = match.groups()
                level = len(level)

                keep = True

                if self._whitelist:
                    keep = any(p.fullmatch(header_text) for p in self._whitelist)
                if self._blacklist:
                    keep = not any(p.fullmatch(header_text) for p in self._blacklist)

                while header_stack and not header_stack[-1][0] >= level:
                    header_stack.pop()

                if header_stack and not header_stack[-1][1]:
                    keep = False

                header_stack.append((level, keep_section))
                keep_section = keep

            if keep_section:
                filtered_lines.append(line)
        filtered_md = "\n".join(filtered_lines)

        item.data_object.data = filtered_md
        item.data_object.name = f"{item.data_object.name}_filtered"
        self.logger.debug(f"Filtered {len(md_lines) - len(filtered_lines)} headers")
        return [item]
