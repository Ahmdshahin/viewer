/*
 * Minimal client-side PDF builder used by the Print Layout tool.
 * Embeds a single JPEG (DCTDecode) stretched across a full page.
 * Output is a spec-conformant PDF 1.4 file with a correct xref table.
 */

const enc = new TextEncoder();

export function buildPdfFromJpeg({ jpegDataUrl, widthPx, heightPx, pageWidthPt, pageHeightPt }) {
  const comma = jpegDataUrl.indexOf(",");
  const b64 = comma >= 0 ? jpegDataUrl.slice(comma + 1) : jpegDataUrl;
  const bin = atob(b64);
  const img = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) img[i] = bin.charCodeAt(i);

  const chunks = [];
  const objOffsets = new Array(6).fill(0);
  let pos = 0;

  const writeText = (s) => {
    const bytes = enc.encode(s);
    chunks.push(bytes);
    pos += bytes.length;
  };
  const writeBytes = (b) => {
    chunks.push(b);
    pos += b.length;
  };
  const objStart = (n) => {
    objOffsets[n] = pos;
  };
  const pad10 = (n) => String(n).padStart(10, "0");

  writeText("%PDF-1.4\n%\u00e2\u00e3\u00cf\u00d3\n");

  objStart(1);
  writeText("1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n");

  objStart(2);
  writeText("2 0 obj\n<< /Type /Pages /Kids [3 0 R] /Count 1 >>\nendobj\n");

  objStart(3);
  writeText("3 0 obj\n<< /Type /Page /Parent 2 0 R /MediaBox [0 0 " + pageWidthPt + " " + pageHeightPt + "] /Resources << /XObject << /Im0 5 0 R >> >> /Contents 4 0 R >>\nendobj\n");

  const ops = "q " + pageWidthPt + " 0 0 " + pageHeightPt + " 0 0 cm /Im0 Do Q\n";
  objStart(4);
  writeText("4 0 obj\n<< /Length " + ops.length + " >>\nstream\n");
  writeText(ops);
  writeText("endstream\nendobj\n");

  objStart(5);
  writeText("5 0 obj\n<< /Type /XObject /Subtype /Image /Width " + widthPx + " /Height " + heightPx +
    " /ColorSpace /DeviceRGB /BitsPerComponent 8 /Filter /DCTDecode /Length " + img.length + " >>\nstream\n");
  writeBytes(img);
  writeText("\nendstream\nendobj\n");

  const xrefPos = pos;
  writeText("xref\n0 6\n0000000000 65535 f \n");
  for (let n = 1; n <= 5; n++) writeText(pad10(objOffsets[n]) + " 00000 n \n");
  writeText("trailer\n<< /Size 6 /Root 1 0 R >>\nstartxref\n" + xrefPos + "\n%%EOF");

  const out = new Uint8Array(pos);
  let o = 0;
  for (const c of chunks) {
    out.set(c, o);
    o += c.length;
  }
  return out;
}

export const mmToPt = (mm) => Math.round((mm * 72) / 25.4 * 100) / 100;