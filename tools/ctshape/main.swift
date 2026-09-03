// ctshape -- a CoreText counterpart to `hb-shape`.
//
// Usage:
//   ctshape <font.ttf> <size> <text> [--render out.png]
//
// Prints one line of JSON per run:
//   {"font":"...","glyphs":[{"gid":12,"name":"r.3068.tm1","x":0.0,"y":90.0,"adv":0.0}, ...]}
//
// Positions are reported in em units (upem-normalised) so they can be compared
// directly against hb-shape output.

import CoreText
import CoreGraphics
import Foundation
import ImageIO
import UniformTypeIdentifiers

func die(_ m: String) -> Never {
    FileHandle.standardError.write((m + "\n").data(using: .utf8)!)
    exit(1)
}

let args = CommandLine.arguments
guard args.count >= 4 else { die("usage: ctshape <font> <size> <text> [--render out.png]") }

let fontPath = args[1]
let size = Double(args[2]) ?? 100.0
let text = args[3]
var renderPath: String? = nil
if let i = args.firstIndex(of: "--render"), i + 1 < args.count { renderPath = args[i + 1] }

guard let dataProvider = CGDataProvider(url: URL(fileURLWithPath: fontPath) as CFURL),
      let cgFont = CGFont(dataProvider) else { die("cannot load font \(fontPath)") }
let upem = Double(cgFont.unitsPerEm)
let ctFont = CTFontCreateWithGraphicsFont(cgFont, CGFloat(size), nil, nil)

// no ligature suppression, no kerning override: exercise the default path
let attrs: [CFString: Any] = [kCTFontAttributeName: ctFont]
let attributed = NSAttributedString(string: text,
                                    attributes: attrs as? [NSAttributedString.Key: Any] ?? [:])
let line = CTLineCreateWithAttributedString(attributed)
let runs = CTLineGetGlyphRuns(line) as! [CTRun]

struct G: Encodable { let gid: Int; let name: String; let x: Double; let y: Double; let adv: Double; let cluster: Int }
var out: [G] = []

for run in runs {
    let n = CTRunGetGlyphCount(run)
    var glyphs = [CGGlyph](repeating: 0, count: n)
    var positions = [CGPoint](repeating: .zero, count: n)
    var advances = [CGSize](repeating: .zero, count: n)
    var indices = [CFIndex](repeating: 0, count: n)
    let range = CFRangeMake(0, n)
    CTRunGetGlyphs(run, range, &glyphs)
    CTRunGetPositions(run, range, &positions)
    CTRunGetAdvances(run, range, &advances)
    CTRunGetStringIndices(run, range, &indices)
    let scale = upem / size
    for i in 0..<n {
        let name = (cgFont.name(for: glyphs[i]) as String?) ?? "gid\(glyphs[i])"
        out.append(G(gid: Int(glyphs[i]),
                     name: name,
                     x: (Double(positions[i].x) * scale).rounded(),
                     y: (Double(positions[i].y) * scale).rounded(),
                     adv: (Double(advances[i].width) * scale).rounded(),
                     cluster: Int(indices[i])))
    }
}

let enc = JSONEncoder()
enc.outputFormatting = [.withoutEscapingSlashes]
let payload: [String: Any] = ["font": fontPath, "text": text]
var dict = try! JSONSerialization.jsonObject(with: enc.encode(out)) as! [Any]
var top: [String: Any] = payload
top["glyphs"] = dict
let data = try! JSONSerialization.data(withJSONObject: top, options: [.sortedKeys, .withoutEscapingSlashes])
print(String(data: data, encoding: .utf8)!)

if let rp = renderPath {
    let ascent = Double(CTFontGetAscent(ctFont))
    let descent = Double(CTFontGetDescent(ctFont))
    let width = Double(CTLineGetTypographicBounds(line, nil, nil, nil))
    let margin = 20.0
    let w = Int(width + 2 * margin)
    let h = Int(ascent + descent + 2 * margin)
    let cs = CGColorSpaceCreateDeviceRGB()
    guard let ctx = CGContext(data: nil, width: w, height: h, bitsPerComponent: 8,
                              bytesPerRow: 0, space: cs,
                              bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue)
    else { die("cannot make context") }
    ctx.setFillColor(CGColor(red: 1, green: 1, blue: 1, alpha: 1))
    ctx.fill(CGRect(x: 0, y: 0, width: Double(w), height: Double(h)))
    ctx.textPosition = CGPoint(x: margin, y: margin + descent)
    ctx.setFillColor(CGColor(red: 0, green: 0, blue: 0, alpha: 1))
    CTLineDraw(line, ctx)
    guard let img = ctx.makeImage(),
          let dest = CGImageDestinationCreateWithURL(URL(fileURLWithPath: rp) as CFURL,
                                                     UTType.png.identifier as CFString, 1, nil)
    else { die("cannot write png") }
    CGImageDestinationAddImage(dest, img, nil)
    CGImageDestinationFinalize(dest)
}
_ = dict
