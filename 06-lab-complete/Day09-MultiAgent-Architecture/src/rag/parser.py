from __future__ import annotations


def parse_policy_markdown(markdown_text: str) -> list[dict]:
        chunks = []
        current_h2 = ""
        current_h3 = ""
        current_content = []

        def save_chunk():
            text = "\n".join(current_content).strip()
            if text and (current_h2 or current_h3):
                citation = current_h3 if current_h3 else current_h2
                rendered_lines = []
                if current_h2:
                    rendered_lines.append(f"## {current_h2}")
                if current_h3:
                    rendered_lines.append(f"### {current_h3}")
                rendered_lines.append(text)
                
                chunks.append({
                    "section_h2": current_h2,
                    "section_h3": current_h3,
                    "citation": citation,
                    "rendered_text": "\n\n".join(rendered_lines)
                })
            current_content.clear()

        for line in markdown_text.splitlines():
            if line.startswith("## "):
                save_chunk()
                current_h2 = line.replace("## ", "", 1).strip()
                current_h3 = ""
            elif line.startswith("### "):
                save_chunk()
                current_h3 = line.replace("### ", "", 1).strip()
            else:
                current_content.append(line)
                
        save_chunk()
        return chunks
