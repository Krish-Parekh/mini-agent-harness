from support import load, stub

stub("logfire", "langchain_text_splitters")
chunker = load("chunker", "src/services/ingestion/chunking/chunker.py")

for size, overlap in ((100, 100), (100, 150)):
    try:
        chunker.Chunker(chunk_size=size, overlap=overlap)
    except ValueError:
        continue
    raise SystemExit(f"Chunker(chunk_size={size}, overlap={overlap}) did not raise ValueError")

chunker.Chunker(chunk_size=100, overlap=10)
