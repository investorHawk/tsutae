// PDF の各ページを PNG にする（macOS の PDFKit。2 倍の解像度）。docs/eval/d4-regimen-paper/README.md の手順の 3.
// 使い方: swift pdf2png.swift 入力.pdf 出力の頭  →  出力の頭-p1.png, -p2.png …
import AppKit
import PDFKit
let args = CommandLine.arguments
guard args.count == 3, let doc = PDFDocument(url: URL(fileURLWithPath: args[1])) else {
  fatalError("usage: swift pdf2png.swift in.pdf out-prefix")
}
for i in 0..<doc.pageCount {
  let page = doc.page(at: i)!
  let box = page.bounds(for: .mediaBox)
  let scale: CGFloat = 2
  let rep = NSBitmapImageRep(
    bitmapDataPlanes: nil, pixelsWide: Int(box.width * scale), pixelsHigh: Int(box.height * scale),
    bitsPerSample: 8, samplesPerPixel: 4, hasAlpha: true, isPlanar: false,
    colorSpaceName: .deviceRGB, bytesPerRow: 0, bitsPerPixel: 0)!
  let ctx = NSGraphicsContext(bitmapImageRep: rep)!.cgContext
  ctx.setFillColor(.white)
  ctx.fill(CGRect(x: 0, y: 0, width: box.width * scale, height: box.height * scale))
  ctx.scaleBy(x: scale, y: scale)
  page.draw(with: .mediaBox, to: ctx)
  try! rep.representation(using: .png, properties: [:])!
    .write(to: URL(fileURLWithPath: "\(args[2])-p\(i + 1).png"))
}
