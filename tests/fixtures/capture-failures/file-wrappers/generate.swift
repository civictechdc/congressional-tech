import Foundation
let cases: [(String, String, Data)] = [
    ("ascii-small", "test.pdf", Data("%PDF-small\n".utf8)),
    ("ascii-empty", "empty.pdf", Data()),
    ("unicode-small", "Témoignage 日本語.pdf", Data("%PDF-unicode\n".utf8)),
    ("unicode-empty", "空.pdf", Data()),
    ("ascii-large", "large.pdf", Data(repeating: 65, count: 20000)),
]
let out = URL(fileURLWithPath: CommandLine.arguments[1])
for (id, name, bytes) in cases {
    let wrapper = FileWrapper(regularFileWithContents: bytes)
    wrapper.preferredFilename = name
    guard let serialized = wrapper.serializedRepresentation,
          let decoded = FileWrapper(serializedRepresentation: serialized),
          let recovered = decoded.regularFileContents else { fatalError("roundtrip failed") }
    try serialized.write(to: out.appendingPathComponent(id + ".rtfd"))
    try recovered.write(to: out.appendingPathComponent(id + ".expected"))
    let row: [String: Any] = ["id": id, "name": name, "decoded_name": decoded.preferredFilename ?? "", "bytes": recovered.count, "wrapper_bytes": serialized.count, "roundtrip_equal": bytes == recovered]
    print(String(data: try JSONSerialization.data(withJSONObject: row, options: [.sortedKeys]), encoding: .utf8)!)
}
