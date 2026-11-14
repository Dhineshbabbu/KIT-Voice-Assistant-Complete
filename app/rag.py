"""Small, optional PDF knowledge-base helper.

Documents are downloaded only from the KIT documents endpoint. PDFs are extracted and
searched locally with simple token overlap. This is a lightweight fallback, not vector RAG.
"""
import re, json
from pathlib import Path
from pypdf import PdfReader
from app.config import settings
from app.college import CollegeClient

def _chunks(text, size=900, overlap=120):
    text = re.sub(r"\s+", " ", text).strip()
    out=[]
    start=0
    while start < len(text):
        end=min(len(text), start+size)
        out.append(text[start:end])
        if end == len(text): break
        start=max(0, end-overlap)
    return out

async def refresh_documents():
    if not settings.enable_document_rag: return {"indexed":0,"reason":"disabled"}
    listing = await CollegeClient().documents()
    items = listing if isinstance(listing,list) else listing.get("documents", listing.get("items", []))
    cache=Path(settings.document_cache_dir); cache.mkdir(parents=True,exist_ok=True)
    count=0
    for item in items:
        doc_id=item.get("id")
        if doc_id is None: continue
        try:
            content, _ = await CollegeClient().document_file(doc_id)
            path=cache/f"{doc_id}.pdf"; path.write_bytes(content)
            reader=PdfReader(str(path))
            text="\n".join(page.extract_text() or "" for page in reader.pages)
            chunks=_chunks(text)
            (cache/f"{doc_id}.json").write_text(json.dumps({"title":item.get("title",""),"chunks":chunks},ensure_ascii=False),encoding="utf-8")
            count += len(chunks)
        except Exception:
            # A single inaccessible/unsupported PDF must not break the assistant.
            continue
    return {"indexed_chunks":count}

def search_documents(query, top_k=4):
    cache=Path(settings.document_cache_dir)
    terms={t.lower() for t in re.findall(r"[a-zA-Z0-9]{3,}",query)}
    ranked=[]
    for path in cache.glob("*.json"):
        try: doc=json.loads(path.read_text(encoding="utf-8"))
        except Exception: continue
        for chunk in doc.get("chunks",[]):
            words=set(re.findall(r"[a-zA-Z0-9]{3,}",chunk.lower()))
            score=len(terms & words)
            if score: ranked.append((score,doc.get("title","KIT document"),chunk))
    ranked.sort(reverse=True,key=lambda x:x[0])
    return [{"title":t,"text":c,"score":s} for s,t,c in ranked[:top_k]]
