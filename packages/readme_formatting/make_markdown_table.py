import re


# Converts markdown-style bold and italic text to corresponding HTML tags
def htmlify_markdown(text):
    text = re.sub(r"\*\*(.*?)\*\*", r"<b>\1</b>", text)
    text = re.sub(r"(?<!\*)\*(?!\*)(.*?)\*(?!\*)", r"<i>\1</i>", text)
    return text


# Splits a list of lines into blocks using the provided separator (default is markdown "## ")
def split_into_blocks(input, sep="## "):
    blocks = []
    current_block = []

    for line in input:
        if line.startswith(sep):
            if current_block:
                blocks.append(current_block)
                current_block = []
        current_block.append(line)

    if current_block:
        blocks.append(current_block)

    return blocks


# Converts a markdown block into a pure markdown table format with custom formatting
def process_block_to_md(block):
    block = [item for item in block if (item != "\n" and item != "---\n")]
    print("Working on:", block[0])

    # Extract each project row from the block by further splitting on "### "
    rows = split_into_blocks(block[2:], sep="### ")
    # Strip leading numbered headings from project rows
    for i, row in enumerate(rows):
        if row and row[0].startswith("### "):
            row[0] = re.sub(r"^###\s*\d+\.\s*", "", row[0])
    title = block[0]
    focus = block[1]

    # Define the headers of the markdown table
    nbsp = "    "
    icon = "🔹"

    headers = [
        "Name",
        "Solution",
        "Problem",
        "Value",
        "Level of Effort (1-5)",
        "Potential Impact",
        "Existing Resources",
    ]
    output = (
        f"{title}\n{focus}\n"
        + " | ".join(headers)
        + "\n"
        + " | ".join(["---" for _ in headers])
        + "\n"
    )

    # Process each project row
    for row in rows:
        bullets = split_into_blocks(row[:], "* ")

        # Process each column in the row by matching it with the appropriate header
        for bullet in bullets:
            beginning = bullet[0]

            # catch whichever header this column is, check them all
            #  not very efficient tbh
            for header in headers:
                beginning = beginning.replace(f"*   **{header}:**", "").strip()

            # determine if the top level is itself a bulleted list (like for "Value" column)
            if len(bullets[0]) > 1:
                output += f"{nbsp}{icon}{beginning}<br>"
            else:
                output += beginning

            # Handle any sub-bullets (nested bullet points) for detailed info like steps
            sub_bullets = split_into_blocks(bullet[1:], "    *")
            for sub_bullet in sub_bullets:
                output += (
                    sub_bullet[0]
                    .replace("    *   ", f"<br> {nbsp}{icon} ")
                    .replace("\n", "")
                )
                for sub_sub_bullet in sub_bullet[1:]:
                    output += sub_sub_bullet.replace(
                        "        *   ", f"<br> {nbsp}{nbsp}{nbsp}{icon}{icon} "
                    ).replace("\n", "")

            # end this column entry
            output += " | "

        # end this row entry
        output += "\n"

    return output


# Converts a markdown block into an HTML table with collapsible details
def process_block_to_html(block):
    block = [item for item in block if (item != "\n" and item != "---\n")]
    print("Working on:", block[0])

    # Extract each project row from the block
    rows = split_into_blocks(block[2:], sep="### ")
    for i, row in enumerate(rows):
        if row and row[0].startswith("### "):
            row[0] = re.sub(r"^###\s*\d+\.\s*", "", row[0])
    title = block[0]
    focus = block[1]

    headers = [
        "Name",
        "Problem",
        "Solution",
        "Value",
        "Level of Effort (1-5)",
        "Potential Impact",
        "Notes",
    ]
    output = f"{title.strip()}\n{focus.strip()}\n\n"
    output += (
        "<table>\n<thead><tr>"
        + "".join(f"<th>{h}</th>" for h in headers)
        + "</tr></thead>\n<tbody>\n"
    )

    icon = "🔹"
    # Process each project into a table row
    for row in rows:
        bullets = split_into_blocks(row[:], "* ")
        output += "<tr>"
        header = ""
        found = False
        # Match each bullet to its corresponding header and build the cell content
        for bullet in bullets:
            beginning = bullet[0]
            for header in headers:
                if header in beginning:
                    found = True
                    beginning = beginning.replace(f"*   **{header}:**", "").strip()
                    break
            print(header)

            sub_bullets = split_into_blocks(bullet[1:], "    *")
            content = beginning
            for sub_bullet in sub_bullets:
                content += f"<br> {icon}" + htmlify_markdown(
                    sub_bullet[0].strip().replace("* ", "", 1)
                )
                for sub_sub_bullet in sub_bullet[1:]:
                    content += f"<br>&nbsp;&nbsp; {icon}{icon}" + htmlify_markdown(
                        sub_sub_bullet.strip().replace("* ", "", 1)
                    )

            if found and header in ["Solution", "Value"]:
                content = f"<details><summary>{header}</summary>{content}</details>"
            elif found and header in ["Problem"]:
                content = (
                    f"<details open><summary>{header}</summary>{content}</details>"
                )
            output += f"<td>{content}</td>"
        output += (
            "\n"
            "<td> <!-- TODO: Level of Effort (1-5) --> </td>\n"
            "<td> <!-- TODO: Potential Impact --></td>\n"
            "<td>\n"
            "  <details>\n"
            "    <summary>Notes</summary>\n"
            "    <!-- TODO: Add notes here -->\n"
            "  </details>\n"
            "</td>\n"
        )
        output += "</tr>\n"
    output += "</tbody>\n</table>\n\n"
    return output


# Entry point: reads markdown input, processes each block, writes both markdown and HTML outputs
def main():
    with open("markdown/input.md", "r") as handle:
        input = handle.readlines()

    blocks = split_into_blocks(input)

    with open("markdown/output.md", "w") as handle:
        for block in blocks:
            handle.write(process_block_to_md(block))

    with open("markdown/output.html", "w") as handle:
        for block in blocks:
            handle.write(process_block_to_html(block))


if __name__ == "__main__":
    main()
