import pandas as pd



def main():

    df = pd.read_csv('csv/gdrive.csv')
    df = df.iloc[:, 1:-1]

    nbsp = '    '

    with open("markdown/output.md", 'w+') as handle:
        handle.write(f"{'|'.join(list(df.keys()))}\n")
        handle.write(f"{'|'.join(['---' for _ in df.keys()])}\n")
        for _, row in df.iterrows():
            formatted_values = []
            for val in row.values:
                val_str = str(val).strip()
                depth = 0
                if '\n' in val_str:
                    bullets = []
                    for line in val_str.split('\n'):
                        if line.strip():
                            indent = nbsp * depth
                            bullets.append(f"{indent}🔹 {line.strip()}")
                        depth += line.strip().endswith(':')
                    formatted_values.append('<br>'.join(bullets))
                else:
                    formatted_values.append(val_str)
            handle.write(f"{'|'.join(formatted_values)}\n")

if __name__ == '__main__':
    main()