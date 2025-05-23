import re
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

def process_block_to_md(block):

    block = [ item for item in block if (item != '\n' and item != '---\n')]
    print('Working on:', block[0])

    rows = split_into_blocks(block[2:],sep='### ')
    # Remove any leading numbered headings like "### 1. "
    for i, row in enumerate(rows):
        if row and row[0].startswith("### "):
            row[0] = re.sub(r'^###\s*\d+\.\s*', '', row[0])
    title = block[0]
    focus = block[1]

    nbsp = '    '
    icon = "🔹"

    headers = ['Name', 'Solution', 'Problem', 'Value', 'Level of Effort (1-5)', 'Potential Impact', 'Existing Resources']
    output = f'{title}\n{focus}\n' + " | ".join(headers) + "\n" + " | ".join(["---" for _ in headers]) + "\n"

    ## for each project
    for row in rows:
        bullets = split_into_blocks(row[:], '* ')

        ## for each column in the table
        for bullet in bullets:
            beginning = bullet[0]

            ## catch whichever header this column is, check them all
            ##  not very efficient tbh
            for header in headers:
                beginning = beginning.replace(f"*   **{header}:**",'').strip()

            ## determine if the top level is itself a bulleted list (like for "Value" column)
            if len(bullets[0]) > 1:
                output += f"{nbsp}{icon}{beginning}<br>"
            else: output += beginning
            
            ## identify any sub-bullets for this column entry
            ##  e.g. steps for the "Solution" column
            sub_bullets = split_into_blocks(bullet[1:], '    *')
            for sub_bullet in sub_bullets:
                output += sub_bullet[0].replace("    *   ",f"<br> {nbsp}{icon} ").replace('\n','')
                for sub_sub_bullet in sub_bullet[1:]:
                    output+= sub_sub_bullet.replace("        *   ",f"<br> {nbsp}{nbsp}{nbsp}{icon}{icon} ").replace('\n','')

            ## end this column entry
            output += " | "

        ## end this row entry
        output+="\n"

    return output

def main():

    with open("markdown/input.md",'r') as handle:
        input = handle.readlines()
    
    blocks = split_into_blocks(input)

    with open("markdown/output.md",'w') as handle:
        for block in blocks:
            handle.write(process_block_to_md(block))

if __name__ == '__main__':
    main()