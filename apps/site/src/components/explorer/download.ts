/** Output encoding is separate from the injected archive reader's storage format. */
export function downloadJson(filename: string, document: unknown): void {
  const url = URL.createObjectURL(new Blob([JSON.stringify(document, null, 2)], { type: 'application/json' }));
  const anchor = window.document.createElement('a');
  anchor.href = url;
  anchor.download = filename;
  window.document.body.append(anchor);
  anchor.click();
  anchor.remove();
  // Give the browser time to start the download before releasing its bytes.
  window.setTimeout(() => URL.revokeObjectURL(url), 1_000);
}
